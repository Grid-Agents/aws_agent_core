#!/usr/bin/env python3
"""Build a golden evaluation set for the Grid agent without manual authoring.

Pipeline (see docs/golden_set.md for the design rationale):

  1. Stratified sampling  - mechanical, seeded. Evidence is sampled directly from
     the raw corpus (manifest.jsonl), never through the agent's own retrieval
     index, so the eval cannot be biased toward what the agent already finds well.
  2. Evidence-first generation - Claude writes a question + answer + supporting
     quote from *only* the sampled page/figure.
  3. Independent verification - two filters run as fresh, separate Claude calls:
       * grounding   - is the answer fully supported by the cited evidence?
       * closed-book - can the question be answered with no evidence at all?
                       If yes, it tests world knowledge, not retrieval -> discard.
  4. Storage - survivors are written with evidence anchored to (document_id,
     page, char span / figure path) plus content hashes, so evidence stays
     verifiable even if the corpus is re-parsed. A human-review markdown and a
     rejected-candidates log are written alongside.

Generation and verification share no code, prompts, or context with the agent
under test. Run `--dry-run` first to inspect sampling with zero API spend.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app" / "GridAgentCore"
sys.path.insert(0, str(APP_ROOT))

from grid_agent_core.corpus import document_text, load_manifest  # noqa: E402
from grid_agent_core.models import DocumentRecord, FigureRecord  # noqa: E402

DEFAULT_MODEL = "claude-opus-4-8"
# A page shorter than this is almost always a title page, TOC stub, or blank -
# poor evidence for a question. Skip them during sampling.
MIN_PAGE_CHARS = 350
MAX_CONTEXT_CHARS = 3500  # cap page text sent to the model per evidence unit


# --------------------------------------------------------------------------- #
# Evidence + candidate data structures
# --------------------------------------------------------------------------- #
@dataclass
class EvidenceUnit:
    """One anchored piece of evidence: a page span or a figure."""

    document_id: str
    title: str
    category: str
    kind: str  # "text" | "figure"
    page: int
    char_start: int | None = None
    char_end: int | None = None
    text: str = ""
    text_sha256: str = ""
    figure_id: str = ""
    figure_path: str = ""
    figure_sha256: str = ""
    figure_description: str = ""
    image_media_type: str = "image/jpeg"
    _image_b64: str = field(default="", repr=False)

    def to_anchor(self) -> dict:
        anchor = {
            "document_id": self.document_id,
            "title": self.title,
            "page": self.page,
            "kind": self.kind,
        }
        if self.kind == "text":
            anchor.update(
                char_start=self.char_start,
                char_end=self.char_end,
                text_sha256=self.text_sha256,
            )
        else:
            anchor.update(
                figure_id=self.figure_id,
                figure_path=self.figure_path,
                image_sha256=self.figure_sha256,
            )
        return anchor


@dataclass
class Slot:
    """A planned generation task: which document/modality/type to produce."""

    modality: str  # "text" | "figure" | "multihop"
    question_type: str
    evidence: list[EvidenceUnit]


@dataclass
class Candidate:
    slot: Slot
    question_type: str = ""  # the type actually written (defaults to the slot's requested type)
    question: str = ""
    answer: str = ""
    supporting_quotes: list[str] = field(default_factory=list)
    rejected_reason: str = ""
    grounding: dict = field(default_factory=dict)
    closed_book: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Step 1 - stratified sampling (mechanical, no LLM)
# --------------------------------------------------------------------------- #
def _page_text(full_text: str, page) -> str:
    return full_text[page.start_char : page.end_char].strip()


def _usable_pages(record: DocumentRecord, full_text: str) -> list:
    return [p for p in record.pages if len(_page_text(full_text, p)) >= MIN_PAGE_CHARS]


def _text_evidence(record: DocumentRecord, full_text: str, page) -> EvidenceUnit:
    body = _page_text(full_text, page)[:MAX_CONTEXT_CHARS]
    return EvidenceUnit(
        document_id=record.document_id,
        title=record.title,
        category=record.category,
        kind="text",
        page=page.page,
        char_start=page.start_char,
        char_end=page.end_char,
        text=body,
        text_sha256=page.text_sha256,
    )


def _figure_evidence(
    artifact_dir: Path, record: DocumentRecord, full_text: str, figure: FigureRecord
) -> EvidenceUnit | None:
    image_path = artifact_dir / figure.image_path
    if not image_path.exists():
        return None
    page = next((p for p in record.pages if p.page == figure.page), None)
    context = _page_text(full_text, page)[:MAX_CONTEXT_CHARS] if page else ""
    return EvidenceUnit(
        document_id=record.document_id,
        title=record.title,
        category=record.category,
        kind="figure",
        page=figure.page,
        char_start=page.start_char if page else None,
        char_end=page.end_char if page else None,
        text=context,
        text_sha256=page.text_sha256 if page else "",
        figure_id=figure.figure_id,
        figure_path=figure.image_path,
        figure_sha256=figure.image_sha256,
        figure_description=figure.description,
        image_media_type=figure.content_type or "image/jpeg",
        _image_b64=base64.b64encode(image_path.read_bytes()).decode("ascii"),
    )


# Question types cycled through per modality, so the set spans question shapes
# rather than clustering on whatever the model finds easiest to write.
TEXT_TYPES = ("factoid", "numerical", "definitional", "procedural")
FIGURE_TYPES = ("figure_reading", "figure_numerical")
MULTIHOP_TYPES = ("multi_hop",)


def plan_slots(
    records: list[DocumentRecord],
    full_texts: dict[str, str],
    artifact_dir: Path,
    *,
    target: int,
    oversample: float,
    figure_fraction: float,
    multihop_fraction: float,
    rng: random.Random,
) -> list[Slot]:
    """Build the candidate generation plan via a fixed coverage matrix."""
    n_total = max(1, round(target * oversample))
    n_figure = round(n_total * figure_fraction)
    n_multihop = round(n_total * multihop_fraction)
    n_text = n_total - n_figure - n_multihop

    docs_with_figs = [
        r for r in records if any((artifact_dir / f.image_path).exists() for f in r.figures)
    ]
    docs_multi = [r for r in records if len(_usable_pages(r, full_texts[r.document_id])) >= 2]

    slots: list[Slot] = []

    # Text slots: round-robin across all documents, random page within each.
    used_text: dict[str, set[int]] = {r.document_id: set() for r in records}
    for i in range(n_text):
        record = records[i % len(records)]
        pages = [
            p
            for p in _usable_pages(record, full_texts[record.document_id])
            if p.page not in used_text[record.document_id]
        ]
        if not pages:
            continue
        page = rng.choice(pages)
        used_text[record.document_id].add(page.page)
        slots.append(
            Slot(
                modality="text",
                question_type=TEXT_TYPES[i % len(TEXT_TYPES)],
                evidence=[_text_evidence(record, full_texts[record.document_id], page)],
            )
        )

    # Figure slots: round-robin across documents that actually have figures.
    used_fig: set[str] = set()
    if docs_with_figs:
        for i in range(n_figure):
            record = docs_with_figs[i % len(docs_with_figs)]
            figs = [
                f
                for f in record.figures
                if f.figure_id not in used_fig and (artifact_dir / f.image_path).exists()
            ]
            if not figs:
                continue
            figure = rng.choice(figs)
            used_fig.add(figure.figure_id)
            ev = _figure_evidence(artifact_dir, record, full_texts[record.document_id], figure)
            if ev is None:
                continue
            slots.append(
                Slot(
                    modality="figure",
                    question_type=FIGURE_TYPES[i % len(FIGURE_TYPES)],
                    evidence=[ev],
                )
            )

    # Multi-hop slots: two distinct pages from the same document.
    if docs_multi:
        for i in range(n_multihop):
            record = docs_multi[i % len(docs_multi)]
            pages = _usable_pages(record, full_texts[record.document_id])
            if len(pages) < 2:
                continue
            two = rng.sample(pages, 2)
            slots.append(
                Slot(
                    modality="multihop",
                    question_type="multi_hop",
                    evidence=[
                        _text_evidence(record, full_texts[record.document_id], p) for p in two
                    ],
                )
            )

    rng.shuffle(slots)
    return slots


# --------------------------------------------------------------------------- #
# Claude client + JSON parsing
# --------------------------------------------------------------------------- #
def _make_client():
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise SystemExit("Install the anthropic SDK: `uv sync --extra build`") from exc
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set (source your .env first).")
    # Opus 4.8 is direct-API only here; do NOT use the Bedrock-formatted
    # ANTHROPIC_MODEL from .env. SDK auto-retries 429/5xx.
    return anthropic.Anthropic()


def _complete(client, model: str, system: str, user_content, max_tokens: int) -> str:
    """One stateless completion. No temperature / no thinking (Opus 4.8 rejects
    temperature and runs thinking-off when the field is omitted)."""
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text").strip()


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction - thinking-off Opus may add preamble prose."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from model output:\n{text[:500]}")


def _evidence_blocks(evidence: list[EvidenceUnit], *, include_images: bool) -> list:
    """Render evidence units as Claude content blocks (text, plus images for
    figures when requested)."""
    blocks: list = []
    for idx, ev in enumerate(evidence, start=1):
        label = f"[Evidence {idx}] Document: {ev.title} ({ev.document_id}), page {ev.page}"
        if ev.kind == "figure":
            if include_images and ev._image_b64:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": ev.image_media_type,
                            "data": ev._image_b64,
                        },
                    }
                )
            parts = [label, "This evidence is a FIGURE/DIAGRAM from the document."]
            if ev.figure_description:
                parts.append(f"Figure description (from a vision model):\n{ev.figure_description}")
            if ev.text:
                parts.append(f"Surrounding page text:\n{ev.text}")
            blocks.append({"type": "text", "text": "\n\n".join(parts)})
        else:
            blocks.append({"type": "text", "text": f"{label}\n\n{ev.text}"})
    return blocks


# --------------------------------------------------------------------------- #
# Step 2 - evidence-first generation
# --------------------------------------------------------------------------- #
_GEN_SYSTEM = """You write evaluation questions for a retrieval agent over UK electricity-grid \
documents (legislation, industry codes, standards, engineering recommendations).

You will be given ONE OR MORE pieces of evidence. Write a single question whose answer is \
FULLY contained in the provided evidence, plus the correct answer and the exact supporting \
quote(s) copied verbatim from the evidence.

Hard requirements:
- The answer must be derivable from the evidence ALONE. Do not use outside knowledge.
- The question must be SELF-CONTAINED: answerable by someone who has not been told which \
document it came from. Name the relevant document or authority in the question when the answer \
would otherwise be ambiguous across standards (e.g. "Under the ESQCR, ...", "In the Grid Code, ...").
- Do NOT copy the evidence phrasing verbatim into the question - rephrase.
- Prefer specific, checkable answers (values, thresholds, durations, defined terms, \
named procedures) over vague ones.
- For a multi-hop question, it must genuinely require combining BOTH pieces of evidence.

Question type to write: {question_type}
  factoid        - a specific fact stated in the text
  numerical      - a number, threshold, voltage, frequency, duration, or limit
  definitional   - the meaning of a defined term
  procedural     - a required step, obligation, or condition
  figure_reading - what the figure/diagram shows or labels
  figure_numerical - a value, axis, or quantity read from the figure
  multi_hop      - requires combining both evidence passages

Respond with ONLY a JSON object, no other text. Set "question_type" to the type that best \
describes the question you actually wrote (it may differ from the requested type if the \
evidence better supports another type):
{{"question": "...", "answer": "...", "supporting_quotes": ["verbatim quote", "..."], \
"question_type": "factoid", "answerable_from_evidence": true}}
If you cannot write a sound question from this evidence, return \
{{"answerable_from_evidence": false}}."""


def generate(client, model: str, slot: Slot) -> Candidate:
    cand = Candidate(slot=slot)
    system = _GEN_SYSTEM.format(question_type=slot.question_type)
    content = _evidence_blocks(slot.evidence, include_images=True)
    content.append({"type": "text", "text": "Write the question now."})
    try:
        raw = _complete(client, model, system, content, max_tokens=1400)
        data = _extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        cand.rejected_reason = f"generation_error: {exc}"
        return cand
    if not data.get("answerable_from_evidence", False):
        cand.rejected_reason = "generator_declined: no sound question from evidence"
        return cand
    cand.question = str(data.get("question", "")).strip()
    cand.answer = str(data.get("answer", "")).strip()
    cand.question_type = str(data.get("question_type") or slot.question_type).strip()
    quotes = data.get("supporting_quotes") or []
    cand.supporting_quotes = [str(q).strip() for q in quotes if str(q).strip()]
    if not cand.question or not cand.answer:
        cand.rejected_reason = "generator_incomplete: missing question or answer"
    return cand


# --------------------------------------------------------------------------- #
# Step 3 - independent verification
# --------------------------------------------------------------------------- #
_GROUNDING_SYSTEM = """You are checking whether a question is answerable from the provided \
evidence ALONE. Use only the evidence; ignore any outside knowledge.

Given the evidence and a question, determine:
- Is the question answerable using only this evidence?
- What is the correct answer according to the evidence?

Respond with ONLY a JSON object:
{"answerable": true/false, "evidence_answer": "the answer per the evidence, or empty"}"""


_CLOSED_BOOK_SYSTEM = """Answer the question from your own general knowledge. You have NOT been \
given any source document. If you do not confidently know the answer, respond exactly with \
UNKNOWN.

Respond with ONLY a JSON object:
{"answer": "your answer, or UNKNOWN"}"""


_JUDGE_SYSTEM = """You compare two answers to the same question and decide whether they agree \
in substance (same facts / values / meaning; wording may differ).

Respond with ONLY a JSON object:
{"match": true/false}"""


def _judge_match(client, model: str, question: str, reference: str, candidate_answer: str) -> bool:
    user = (
        f"Question:\n{question}\n\n"
        f"Reference answer:\n{reference}\n\n"
        f"Candidate answer:\n{candidate_answer}\n\n"
        "Do they agree in substance?"
    )
    try:
        data = _extract_json(_complete(client, model, _JUDGE_SYSTEM, user, max_tokens=200))
        return bool(data.get("match", False))
    except Exception:  # noqa: BLE001
        return False


def verify(client, model: str, cand: Candidate) -> Candidate:
    """Run the grounding and closed-book filters. Sets rejected_reason on failure."""
    # --- grounding: answer must be supported by the cited evidence ---
    g_content = _evidence_blocks(cand.slot.evidence, include_images=True)
    g_content.append({"type": "text", "text": f"Question:\n{cand.question}"})
    try:
        g = _extract_json(_complete(client, model, _GROUNDING_SYSTEM, g_content, max_tokens=700))
    except Exception as exc:  # noqa: BLE001
        cand.rejected_reason = f"grounding_error: {exc}"
        return cand
    cand.grounding = g
    if not g.get("answerable", False):
        cand.rejected_reason = "ungrounded: not answerable from cited evidence"
        return cand
    if not _judge_match(client, model, cand.question, cand.answer, str(g.get("evidence_answer", ""))):
        cand.rejected_reason = "answer_mismatch: golden answer not supported by evidence"
        return cand

    # --- closed-book: must NOT be answerable without the evidence ---
    try:
        cb = _extract_json(
            _complete(client, model, _CLOSED_BOOK_SYSTEM, cand.question, max_tokens=600)
        )
    except Exception as exc:  # noqa: BLE001
        cand.rejected_reason = f"closed_book_error: {exc}"
        return cand
    cand.closed_book = cb
    cb_answer = str(cb.get("answer", "")).strip()
    if cb_answer and cb_answer.upper() != "UNKNOWN":
        if _judge_match(client, model, cand.question, cand.answer, cb_answer):
            cand.rejected_reason = "closed_book_answerable: solvable without retrieval"
            return cand
    return cand


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _record(cand: Candidate, gen_model: str, ver_model: str, revision: str, idx: int) -> dict:
    return {
        "id": f"golden-{idx:03d}",
        "question": cand.question,
        "answer": cand.answer,
        "question_type": cand.question_type or cand.slot.question_type,
        "modality": cand.slot.modality,
        "supporting_quotes": cand.supporting_quotes,
        "evidence": [ev.to_anchor() for ev in cand.slot.evidence],
        "verification": {
            "grounded": True,
            "grounding_evidence_answer": cand.grounding.get("evidence_answer", ""),
            "closed_book_answer": cand.closed_book.get("answer", ""),
        },
        "generator_model": gen_model,
        "verifier_model": ver_model,
        "artifact_revision": revision,
    }


def write_outputs(
    out_dir: Path, survivors: list[Candidate], rejected: list[Candidate], *, gen_model, ver_model, revision
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    golden_path = out_dir / "golden_set.jsonl"
    with golden_path.open("w", encoding="utf-8") as fh:
        for i, cand in enumerate(survivors, start=1):
            fh.write(json.dumps(_record(cand, gen_model, ver_model, revision, i), ensure_ascii=True) + "\n")

    rejected_path = out_dir / "rejected.jsonl"
    with rejected_path.open("w", encoding="utf-8") as fh:
        for cand in rejected:
            fh.write(
                json.dumps(
                    {
                        "modality": cand.slot.modality,
                        "question_type": cand.slot.question_type,
                        "question": cand.question,
                        "answer": cand.answer,
                        "reason": cand.rejected_reason,
                        "evidence": [ev.to_anchor() for ev in cand.slot.evidence],
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    review_path = out_dir / "review.md"
    lines = [
        "# Golden set - human review",
        "",
        f"{len(survivors)} candidates survived automated filtering. Tick the box to approve, "
        "or strike the question and note why. Check that the evidence quote actually supports the answer.",
        "",
    ]
    for i, cand in enumerate(survivors, start=1):
        anchors = "; ".join(
            f"{ev.title} p.{ev.page}" + (f" fig {ev.figure_id}" if ev.kind == "figure" else "")
            for ev in cand.slot.evidence
        )
        lines += [
            f"## golden-{i:03d}  ·  {cand.slot.modality}/{cand.question_type or cand.slot.question_type}",
            f"- [ ] **Q:** {cand.question}",
            f"  - **A:** {cand.answer}",
            f"  - **Evidence:** {anchors}",
        ]
        for q in cand.supporting_quotes:
            lines.append(f"  - **Quote:** “{q}”")
        lines.append("")
    review_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nWrote {len(survivors)} golden questions -> {golden_path}")
    print(f"Wrote {len(rejected)} rejected candidates -> {rejected_path}")
    print(f"Wrote review checklist -> {review_path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact-dir", type=Path, default=REPO_ROOT / ".grid_artifacts")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / ".grid_artifacts" / "golden_set")
    parser.add_argument("--target", type=int, default=18, help="Desired final question count.")
    parser.add_argument("--oversample", type=float, default=2.5, help="Candidates generated per final question.")
    parser.add_argument("--figure-fraction", type=float, default=0.35)
    parser.add_argument("--multihop-fraction", type=float, default=0.12)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generator-model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--verifier-model",
        default=DEFAULT_MODEL,
        help="Model for verification. Set a different model than the generator for stronger independence.",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="Plan + extract evidence only; no API calls.")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ModuleNotFoundError:
        pass

    records = load_manifest(args.artifact_dir)
    full_texts = {r.document_id: document_text(args.artifact_dir, r) for r in records}
    revision = (args.artifact_dir / "artifact_revision.txt").read_text(encoding="utf-8").strip() if (
        args.artifact_dir / "artifact_revision.txt"
    ).exists() else ""

    rng = random.Random(args.seed)
    slots = plan_slots(
        records,
        full_texts,
        args.artifact_dir,
        target=args.target,
        oversample=args.oversample,
        figure_fraction=args.figure_fraction,
        multihop_fraction=args.multihop_fraction,
        rng=rng,
    )

    by_mod: dict[str, int] = {}
    for s in slots:
        by_mod[s.modality] = by_mod.get(s.modality, 0) + 1
    print(f"Planned {len(slots)} candidate slots: {by_mod}")
    print(f"Coverage across {len(records)} documents.")

    if args.dry_run:
        print("\n--- DRY RUN: sample slots ---")
        for s in slots[:8]:
            ev = s.evidence[0]
            preview = (ev.figure_description or ev.text)[:140].replace("\n", " ")
            print(f"  [{s.modality}/{s.question_type}] {ev.title} p.{ev.page}: {preview}...")
        print("\nNo API calls made. Re-run without --dry-run to generate and verify.")
        return

    client = _make_client()
    lock = threading.Lock()
    done = {"n": 0}

    def run_one(slot: Slot) -> Candidate:
        cand = generate(client, args.generator_model, slot)
        if not cand.rejected_reason:
            cand = verify(client, args.verifier_model, cand)
        with lock:
            done["n"] += 1
            status = "ok" if not cand.rejected_reason else cand.rejected_reason.split(":")[0]
            print(f"  [{done['n']}/{len(slots)}] {slot.modality}/{slot.question_type} -> {status}")
        return cand

    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_one, s) for s in slots]
        for fut in as_completed(futures):
            candidates.append(fut.result())

    survivors = [c for c in candidates if not c.rejected_reason][: args.target]
    rejected = [c for c in candidates if c.rejected_reason]
    write_outputs(
        args.out_dir,
        survivors,
        rejected,
        gen_model=args.generator_model,
        ver_model=args.verifier_model,
        revision=revision,
    )


if __name__ == "__main__":
    main()
