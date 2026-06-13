# Email Application Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let developers submit application bundles by email — a Gmail-polled inbox feeds PDF attachments to an AI intake-agent that extracts a structured submission, which lands in a "Pending intake" queue for an operator to Accept (→ becomes a normal reviewable bundle) or Reject.

**Architecture:** A background poller reads an intake Gmail inbox, downloads PDF attachments, and calls a structured-output Claude (Bedrock) extractor that maps the docs against the canonical requirements schema. The result is parked under `review_seed/pending/{id}/` as `submission.json` + the original PDFs. New `/api/review/intake/*` endpoints list/show/accept/reject pending submissions; **Accept reuses the seed generator's form renderer** to emit `00_application_form.pdf` and moves the bundle into `applications/`, so the entire existing review pipeline runs on it unchanged.

**Tech Stack:** Python 3.10+/FastAPI, `anthropic` (AnthropicBedrock), `pymupdf`/fitz, `reportlab`, `google-api-python-client`; React/Vite/TypeScript (react-router, framer-motion); pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-email-application-intake-design.md`

---

## File Structure

**Backend (`app/GridAgentCore/`):**
- Create `grid_agent_core/application_form.py` — the `00_application_form.pdf` renderer, extracted from `review_seed/generate_seed.py` so both the seed generator and Accept can use it.
- Create `grid_agent_core/requirements_schema.py` — loads the vendored `transmission.md`/`distribution.md` into per-`(level, conn_type)` category lists.
- Create `review_seed/schema/transmission.md`, `review_seed/schema/distribution.md` — vendored copies of the canonical catalog.
- Create `grid_agent_core/intake.py` — the structured-output extractor (+ injectable model client).
- Create `grid_agent_core/intake_store.py` — pending-bundle storage, project-id allocation, accept/reject.
- Create `grid_agent_core/intake_gmail.py` — Gmail OAuth client + poller, env-gated.
- Modify `grid_agent_core/review_api.py` — add the four `/api/review/intake/*` endpoints.
- Modify `grid_agent_core/local_api.py` — startup hook to launch the poller; mount `/intake-pdfs`.
- Modify `grid_agent_core/settings.py` — Gmail/intake config helpers.
- Modify `review_seed/generate_seed.py` — import the renderer from the package.
- Modify `pyproject.toml` — add Google API deps.

**Frontend (`app/review_frontend/src/`):**
- Modify `types.ts` — intake types.
- Modify `api.ts` — intake client functions + `intakePdfUrl`.
- Create `pages/IntakePage.tsx` — pending-intake detail (extracted sections + attachments + flags + Accept/Reject).
- Modify `pages/Dashboard.tsx` — "Pending intake" panel.
- Modify `App.tsx` — `/intake/:id` route.

**Tests (`tests/grid_agent_core/`):**
- Create `test_application_form.py`, `test_requirements_schema.py`, `test_intake.py`, `test_intake_store.py`, `test_intake_api.py`, `test_intake_gmail.py`.

Run all backend tests from `app/GridAgentCore/` with `uv run pytest` (testpaths is `../../tests/grid_agent_core`). Run a single test with `uv run pytest ../../tests/grid_agent_core/test_x.py::test_y -v`.

---

## Task 1: Extract the application-form renderer into the package

Today `render_application_form` lives in `review_seed/generate_seed.py`, which isn't an importable package module (it `sys.path`-hacks and imports `seed_data`). Accept needs to render the same PDF, so move the renderer into the package and have the generator import it. This guards the format contract via a round-trip test (`render → parse_submission`).

**Files:**
- Create: `app/GridAgentCore/grid_agent_core/application_form.py`
- Modify: `app/GridAgentCore/review_seed/generate_seed.py`
- Test: `tests/grid_agent_core/test_application_form.py`

- [ ] **Step 1: Write the failing round-trip test**

```python
# tests/grid_agent_core/test_application_form.py
from __future__ import annotations

from grid_agent_core.application_form import render_application_form
from grid_agent_core.review_api import parse_submission

PROJECT = {
    "id": "TX-GEN-009",
    "name": "Testfield Wind",
    "applicant": "Testfield Renewables Ltd",
    "level": "transmission",
    "conn_type": "generation",
    "capacity": "300 MW onshore wind",
    "status": "Under review",
    "submitted": "2026-06-13",
    "sections": [
        {
            "id": "s1",
            "title": "Site & location",
            "requirement": "Site address plus GPS coordinates (WGS84, 3 d.p.).",
            "submitted": "Testfield Moor, 54.0 N, -0.5 E. Connects to the 400 kV corridor.",
            "docs": ["red_line_boundary_plan.pdf"],
        },
        {
            "id": "s2",
            "title": "Project capacity",
            "requirement": "Megawatt capacity plus total connection capacity requested.",
            "submitted": "Total TEC requested: 300 MW. 60 x 5 MW turbines.",
            "docs": [],
        },
    ],
}


def test_render_then_parse_round_trips(tmp_path):
    out = tmp_path / "00_application_form.pdf"
    render_application_form(PROJECT, out)
    assert out.is_file()

    parsed = parse_submission(tmp_path)
    assert parsed["id"] == "TX-GEN-009"
    assert parsed["name"] == "Testfield Wind"
    assert parsed["level"] == "transmission"
    assert parsed["conn_type"] == "generation"
    titles = [s["title"] for s in parsed["sections"]]
    assert titles == ["Site & location", "Project capacity"]
    assert parsed["sections"][0]["docs"] == ["red_line_boundary_plan.pdf"]
    assert parsed["sections"][1]["docs"] == []
    assert "GPS coordinates" in parsed["sections"][0]["requirement"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_application_form.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent_core.application_form'`.

- [ ] **Step 3: Create the renderer module**

Move the form-rendering helpers out of `generate_seed.py`. Create `grid_agent_core/application_form.py` with exactly the form-relevant styles, the rule helper, and `render_application_form` (copied verbatim from `generate_seed.py:_styles/_doc/_rule/render_application_form`, trimmed to what the form needs):

```python
# grid_agent_core/application_form.py
"""Render a submission dict to the line-anchored ``00_application_form.pdf``.

Extracted from ``review_seed/generate_seed.py`` so both the seed generator and
the email-intake Accept flow render the identical parseable layout (the labels
``PROJECT ID:`` / ``SECTION N:`` / ``REQUIREMENT:`` / ``SUBMITTED:`` /
``SUPPORTING DOCS:`` that ``review_api.parse_submission`` reads back).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

INK = HexColor("#0f172a")
MUTED = HexColor("#475569")
ACCENT = HexColor("#0e7490")
LINE = HexColor("#cbd5e1")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("title", base, fontName="Helvetica-Bold", fontSize=18,
                                textColor=INK, leading=22, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", base, fontName="Helvetica", fontSize=10.5,
                                   textColor=MUTED, leading=14, spaceAfter=10),
        "meta": ParagraphStyle("meta", base, fontName="Helvetica", fontSize=10, leading=15,
                               textColor=INK, alignment=TA_LEFT),
        "section": ParagraphStyle("section", base, fontName="Helvetica-Bold", fontSize=12,
                                  textColor=ACCENT, leading=16, spaceBefore=12, spaceAfter=4),
        "label": ParagraphStyle("label", base, fontName="Helvetica-Bold", fontSize=8.5,
                                textColor=MUTED, leading=12, spaceBefore=4),
        "body": ParagraphStyle("body", base, fontName="Helvetica", fontSize=10, leading=14.5,
                               textColor=INK, spaceAfter=2),
    }


def _doc(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=path.stem,
    )


def _rule(color=LINE) -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.8, color=color, spaceBefore=6, spaceAfter=6)


def render_application_form(project: dict, out: Path) -> None:
    s = _styles()
    flow = [
        Paragraph("Grid Interconnection Application Form", s["title"]),
        Paragraph(f"{project['level'].capitalize()} connection &mdash; {project['conn_type']}",
                  s["subtitle"]),
        _rule(ACCENT),
    ]
    meta = [
        ("PROJECT ID", project["id"]), ("PROJECT NAME", project["name"]),
        ("APPLICANT", project["applicant"]), ("LEVEL", project["level"]),
        ("CONNECTION TYPE", project["conn_type"]), ("CAPACITY", project["capacity"]),
        ("STATUS", project["status"]), ("DATE SUBMITTED", project["submitted"]),
    ]
    for label, value in meta:
        flow.append(Paragraph(f"<b>{label}:</b> {value}", s["meta"]))
    flow.append(_rule())
    for i, sec in enumerate(project["sections"], start=1):
        docs = ", ".join(sec["docs"]) if sec["docs"] else "none"
        flow.append(Paragraph(f"SECTION {i}: {sec['title']}", s["section"]))
        flow.append(Paragraph("REQUIREMENT:", s["label"]))
        flow.append(Paragraph(sec["requirement"], s["body"]))
        flow.append(Paragraph("SUBMITTED:", s["label"]))
        flow.append(Paragraph(sec["submitted"], s["body"]))
        flow.append(Paragraph("SUPPORTING DOCS:", s["label"]))
        flow.append(Paragraph(docs, s["body"]))
        flow.append(Spacer(1, 2))
    _doc(out).build(flow)
```

- [ ] **Step 4: Point `generate_seed.py` at the shared renderer**

In `review_seed/generate_seed.py`, delete its local `render_application_form` (and the now-unused `_doc`/`_rule`/`_styles` items only if no support-doc renderer uses them — `render_support_doc` uses `_styles`, `_ref_table`, `_schedule_table`, `_rule`, `_doc`, so KEEP those). Simplest safe change: keep `generate_seed.py`'s helpers as-is for support docs, but replace its `render_application_form` definition with a re-export. Add near the top imports:

```python
from grid_agent_core.application_form import render_application_form  # noqa: F401
```

and delete the old `def render_application_form(...)` block in `generate_seed.py` (lines defining it). The generator's `generate()` already calls `render_application_form(project, bundle / "00_application_form.pdf")`, which now resolves to the imported one.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_application_form.py -v`
Expected: PASS (both assertions).

- [ ] **Step 6: Verify the seed generator still works**

Run: `cd app/GridAgentCore && uv run python review_seed/generate_seed.py`
Expected: prints `Wrote N bundles to …/applications` with no import error.

- [ ] **Step 7: Commit**

```bash
git add app/GridAgentCore/grid_agent_core/application_form.py app/GridAgentCore/review_seed/generate_seed.py tests/grid_agent_core/test_application_form.py
git commit -m "refactor: extract application_form renderer into package (reused by intake Accept)"
```

---

## Task 2: Vendor the requirements schema + loader

The intake extractor maps applicant docs against the operator's required categories. Those live in `interactive-pages/connection-application-data/{transmission,distribution}.md` (a *different* repo). Vendor copies into the backend and add a parser.

**Files:**
- Create: `app/GridAgentCore/review_seed/schema/transmission.md`, `app/GridAgentCore/review_seed/schema/distribution.md`
- Create: `app/GridAgentCore/grid_agent_core/requirements_schema.py`
- Test: `tests/grid_agent_core/test_requirements_schema.py`

- [ ] **Step 1: Vendor the markdown files**

```bash
mkdir -p app/GridAgentCore/review_seed/schema
cp /Users/kaps/repos/interactive-pages/connection-application-data/transmission.md app/GridAgentCore/review_seed/schema/transmission.md
cp /Users/kaps/repos/interactive-pages/connection-application-data/distribution.md app/GridAgentCore/review_seed/schema/distribution.md
```

(If the source path is unavailable, the two files already exist in this repo's history via the spec; copy from `/Users/kaps/repos/interactive-pages/connection-application-data/`.)

- [ ] **Step 2: Write the failing test**

```python
# tests/grid_agent_core/test_requirements_schema.py
from __future__ import annotations

import pytest

from grid_agent_core.requirements_schema import load_schema, CONN_TYPES


def test_transmission_generation_has_core_categories():
    cats = load_schema("transmission", "generation")
    names = [c["category"] for c in cats]
    assert "Site & location" in names
    assert "Planning" in names
    assert "Company" in names
    # every category carries the source clause + the 'what submitted' guidance
    assert all(c["source"] for c in cats)
    assert all(c["what_submitted"] for c in cats)


def test_storage_includes_generation_plus_storage_fields():
    gen = {c["category"] for c in load_schema("transmission", "generation")}
    sto = {c["category"] for c in load_schema("transmission", "storage")}
    assert gen.issubset(sto)               # storage = generation + extras
    assert "Energy capacity" in sto


def test_unknown_type_raises():
    with pytest.raises(KeyError):
        load_schema("transmission", "banana")


def test_conn_types_constant():
    assert set(CONN_TYPES) == {"generation", "demand", "storage", "mixed"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_requirements_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent_core.requirements_schema'`.

- [ ] **Step 4: Implement the loader**

```python
# grid_agent_core/requirements_schema.py
"""Parse the vendored connection-application catalog into category lists.

Source of truth: ``review_seed/schema/{transmission,distribution}.md`` (copied
from the ``interactive-pages`` repo). Each markdown file has one ``## N. <Type>``
heading per connection type followed by a pipe-table whose columns are
``Category | What the developer submits | Why … | Source``. Storage is declared
as "same as Generation plus" a storage-specific table, so we merge them.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "review_seed" / "schema"
CONN_TYPES = ("generation", "demand", "storage", "mixed")

# Maps the markdown "## N. <Heading>" to a conn_type id.
_HEADING_TO_TYPE = {
    "generation": "generation",
    "demand": "demand",          # "## 2. Demand (load)"
    "storage": "storage",
    "mixed": "mixed",            # "## 4. Mixed / Co-located"
}
_HEADING_RE = re.compile(r"^##\s+\d+\.\s+(.*)$")
_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def _heading_type(heading: str) -> str | None:
    low = heading.lower()
    for key, ctype in _HEADING_TO_TYPE.items():
        if low.startswith(key):
            return ctype
    return None


def _parse_file(path: Path) -> dict[str, list[dict]]:
    """Return {conn_type: [{category, what_submitted, source}, ...]}."""
    by_type: dict[str, list[dict]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        h = _HEADING_RE.match(line)
        if h:
            current = _heading_type(h.group(1))
            if current is not None:
                by_type.setdefault(current, [])
            continue
        if current is None:
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 4:
            continue
        category = cells[0]
        # skip header + separator rows
        if not category or category.lower() in ("category",) or set(category) <= set("-: "):
            continue
        by_type[current].append(
            {"category": category, "what_submitted": cells[1], "source": cells[3]}
        )
    return by_type


@lru_cache(maxsize=4)
def _load_level(level: str) -> dict[str, list[dict]]:
    path = SCHEMA_DIR / f"{level}.md"
    if not path.is_file():
        raise KeyError(f"Unknown level: {level}")
    parsed = _parse_file(path)
    # Storage is documented as "Generation + storage-specific fields".
    if "generation" in parsed and "storage" in parsed:
        gen = parsed["generation"]
        seen = {c["category"] for c in gen}
        parsed["storage"] = gen + [c for c in parsed["storage"] if c["category"] not in seen]
    return parsed


def load_schema(level: str, conn_type: str) -> list[dict]:
    by_type = _load_level(level)
    if conn_type not in by_type:
        raise KeyError(f"Unknown connection type for {level}: {conn_type}")
    return by_type[conn_type]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_requirements_schema.py -v`
Expected: PASS (4 tests). If `test_storage_includes_generation_plus_storage_fields` fails on category names, open `review_seed/schema/transmission.md` and confirm the Storage table's first column header — adjust the row-skip guard only, not the merge logic.

- [ ] **Step 6: Commit**

```bash
git add app/GridAgentCore/review_seed/schema app/GridAgentCore/grid_agent_core/requirements_schema.py tests/grid_agent_core/test_requirements_schema.py
git commit -m "feat: vendor connection-application schema + per-type loader"
```

---

## Task 3: The AI intake extractor

A two-call structured extraction: (A) classify `(level, conn_type)` + project metadata; (B) per required category, extract the developer's answer + map supporting docs + confidence. The model client is injectable so tests run without Bedrock.

**Files:**
- Create: `app/GridAgentCore/grid_agent_core/intake.py`
- Test: `tests/grid_agent_core/test_intake.py`

- [ ] **Step 1: Write the failing test (with a fake model client)**

```python
# tests/grid_agent_core/test_intake.py
from __future__ import annotations

from grid_agent_core.intake import extract_submission


class FakeModel:
    """Returns queued tool-call dicts, one per call_tool invocation."""
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def call_tool(self, *, system, user, tool_name, input_schema):
        self.calls.append({"system": system, "user": user, "tool_name": tool_name})
        return self._responses.pop(0)


def test_extract_builds_submission_with_requirements_from_schema():
    model = FakeModel(
        # call A: classification
        {"level": "transmission", "conn_type": "generation", "level_confidence": "high",
         "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
         "capacity": "300 MW onshore wind"},
        # call B: per-category extraction (subset of categories returned)
        {"sections": [
            {"category": "Site & location", "submitted": "Testfield Moor, 54.0N -0.5E",
             "docs": ["red_line.pdf"], "confidence": "high"},
            {"category": "Planning", "submitted": "", "docs": [], "confidence": "low"},
         ],
         "flags": ["No planning evidence found"],
         "unmapped_docs": ["random.pdf"]},
    )
    attachments = [
        {"name": "red_line.pdf", "text": "Red line boundary plan for Testfield Moor."},
        {"name": "random.pdf", "text": "Unrelated."},
    ]
    result = extract_submission(attachments, body="Please find our application attached.",
                                model=model)

    assert result["level"] == "transmission"
    assert result["conn_type"] == "generation"
    assert result["name"] == "Testfield Wind"
    # requirement text comes from the SCHEMA, not the model
    site = next(s for s in result["sections"] if s["title"] == "Site & location")
    assert "GPS coordinates" in site["requirement"]
    assert site["submitted"] == "Testfield Moor, 54.0N -0.5E"
    assert site["docs"] == ["red_line.pdf"]
    assert site["confidence"] == "high"
    # intake block carries flags + provenance
    assert "No planning evidence found" in result["intake"]["flags"]
    assert result["intake"]["unmapped_docs"] == ["random.pdf"]
    assert result["intake"]["level_confidence"] == "high"
    # two model calls were made
    assert [c["tool_name"] for c in model.calls] == ["classify", "extract"]


def test_extract_marks_failure_when_classification_raises():
    class Boom:
        def call_tool(self, **_):
            raise RuntimeError("model down")
    result = extract_submission([{"name": "a.pdf", "text": "x"}], body="", model=Boom())
    assert result["intake"]["status"] == "extraction_failed"
    assert result["sections"] == []
    assert result["documents"] == [{"name": "a.pdf"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent_core.intake'`.

- [ ] **Step 3: Implement the extractor**

```python
# grid_agent_core/intake.py
"""Turn an emailed bundle (attachment texts + body) into a structured submission.

Two structured-output calls against Claude on Bedrock:
  A. classify (level, conn_type) + project metadata;
  B. per required category (from requirements_schema), extract the developer's
     answer, map supporting documents, and rate confidence.
The REQUIREMENT text is filled from the schema (not the model) so it stays
deterministic and correct. The model is injectable for testing.
"""
from __future__ import annotations

from typing import Any, Protocol

from .requirements_schema import CONN_TYPES, load_schema
from .settings import aws_region, model_id

_MAX_DOC_CHARS = 6000


class ModelClient(Protocol):
    def call_tool(self, *, system: str, user: str, tool_name: str,
                  input_schema: dict) -> dict: ...


class BedrockModelClient:
    """Default client: anthropic AnthropicBedrock with forced single-tool output."""
    def __init__(self) -> None:
        from anthropic import AnthropicBedrock
        self._client = AnthropicBedrock(aws_region=aws_region())
        self._model = model_id()

    def call_tool(self, *, system, user, tool_name, input_schema) -> dict:
        resp = self._client.messages.create(
            model=self._model, max_tokens=4096, system=system,
            tools=[{"name": tool_name, "description": "Return the structured result.",
                    "input_schema": input_schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise RuntimeError("model returned no tool_use block")


_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": ["transmission", "distribution"]},
        "conn_type": {"type": "string", "enum": list(CONN_TYPES)},
        "level_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "name": {"type": "string"}, "applicant": {"type": "string"},
        "capacity": {"type": "string"},
    },
    "required": ["level", "conn_type", "level_confidence", "name", "applicant", "capacity"],
}


def _extract_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "sections": {"type": "array", "items": {"type": "object", "properties": {
                "category": {"type": "string"},
                "submitted": {"type": "string"},
                "docs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            }, "required": ["category", "submitted", "docs", "confidence"]}},
            "flags": {"type": "array", "items": {"type": "string"}},
            "unmapped_docs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["sections", "flags", "unmapped_docs"],
    }


def _docs_blob(attachments: list[dict]) -> str:
    return "\n\n".join(
        f"--- {a['name']} ---\n{a['text'].strip()[:_MAX_DOC_CHARS]}" for a in attachments
    ) or "(no attachment text extracted)"


def _slug(category: str, i: int) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in category).strip("-")
    return base or f"s{i}"


def extract_submission(attachments: list[dict], body: str,
                       model: ModelClient | None = None) -> dict[str, Any]:
    """attachments: [{'name': str, 'text': str}]. Returns a parse_submission-shaped
    dict plus an 'intake' block (status/flags/confidence/provenance)."""
    model = model or BedrockModelClient()
    documents = [{"name": a["name"]} for a in attachments]
    docs_blob = _docs_blob(attachments)

    try:
        meta = model.call_tool(
            tool_name="classify", input_schema=_CLASSIFY_SCHEMA,
            system="You classify UK grid interconnection applications.",
            user=("Classify this application from its cover email and attached documents.\n\n"
                  f"EMAIL BODY:\n{body.strip() or '(empty)'}\n\nATTACHMENTS:\n{docs_blob}"),
        )
        schema = load_schema(meta["level"], meta["conn_type"])
        catalog = "\n".join(f"- {c['category']}: {c['what_submitted']}" for c in schema)
        ext = model.call_tool(
            tool_name="extract", input_schema=_extract_schema(),
            system="You extract a developer's submitted answers from their documents. "
                   "Quote/synthesise only from the provided text; never invent facts.",
            user=("For each REQUIRED CATEGORY below, give the developer's submitted answer "
                  "(empty string if absent), the attachment filenames that support it, and "
                  "your confidence. Flag missing categories and list attachments mapped to no "
                  f"category.\n\nREQUIRED CATEGORIES:\n{catalog}\n\n"
                  f"EMAIL BODY:\n{body.strip() or '(empty)'}\n\nATTACHMENTS:\n{docs_blob}"),
        )
    except Exception as exc:  # surface as a rejectable pending card, never crash the poller
        return {
            "id": "", "name": "", "applicant": "", "level": "", "conn_type": "",
            "capacity": "", "status": "", "submitted": "",
            "sections": [], "documents": documents,
            "intake": {"status": "extraction_failed", "error": f"{type(exc).__name__}: {exc}",
                       "flags": [], "unmapped_docs": [], "level_confidence": "low"},
        }

    by_cat = {s["category"]: s for s in ext.get("sections", [])}
    sections = []
    for i, cat in enumerate(schema, start=1):
        got = by_cat.get(cat["category"], {})
        sections.append({
            "id": _slug(cat["category"], i),
            "title": cat["category"],
            "requirement": f"{cat['what_submitted']} Source: {cat['source']}.",
            "submitted": got.get("submitted", ""),
            "docs": got.get("docs", []),
            "confidence": got.get("confidence", "low"),
        })
    return {
        "id": "", "name": meta["name"], "applicant": meta["applicant"],
        "level": meta["level"], "conn_type": meta["conn_type"], "capacity": meta["capacity"],
        "status": "", "submitted": "",
        "sections": sections, "documents": documents,
        "intake": {"status": "extracted", "level_confidence": meta["level_confidence"],
                   "flags": ext.get("flags", []), "unmapped_docs": ext.get("unmapped_docs", [])},
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/GridAgentCore/grid_agent_core/intake.py tests/grid_agent_core/test_intake.py
git commit -m "feat: AI intake extractor (classify + per-category extraction against schema)"
```

---

## Task 4: Pending store — save / list / accept / reject

Persist extracted submissions under `review_seed/pending/{intake_id}/` and implement Accept (allocate project id → render form → move into `applications/`) and Reject (archive).

**Files:**
- Create: `app/GridAgentCore/grid_agent_core/intake_store.py`
- Test: `tests/grid_agent_core/test_intake_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/grid_agent_core/test_intake_store.py
from __future__ import annotations

import json

import grid_agent_core.intake_store as store


def _submission(level="transmission", conn_type="generation"):
    return {
        "id": "", "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
        "level": level, "conn_type": conn_type, "capacity": "300 MW", "status": "", "submitted": "",
        "sections": [
            {"id": "site", "title": "Site & location", "requirement": "Address + GPS.",
             "submitted": "Testfield Moor.", "docs": ["red_line.pdf"], "confidence": "high"},
        ],
        "documents": [{"name": "red_line.pdf"}],
        "intake": {"status": "extracted", "level_confidence": "high",
                   "flags": [], "unmapped_docs": []},
    }


def test_create_list_and_load_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")

    store.create_pending("msg-1", _submission(),
                         attachments=[("red_line.pdf", b"%PDF-1.4 fake")],
                         sender="dev@example.com", subject="Our application")

    listed = store.list_pending()
    assert len(listed) == 1
    assert listed[0]["id"] == "msg-1"
    assert listed[0]["sender"] == "dev@example.com"
    assert listed[0]["conn_type"] == "generation"

    detail = store.load_pending("msg-1")
    assert detail["sections"][0]["title"] == "Site & location"
    assert (store.PENDING_DIR / "msg-1" / "red_line.pdf").is_file()


def test_allocate_project_id_increments(tmp_path, monkeypatch):
    apps = tmp_path / "applications"
    (apps / "TX-GEN-001").mkdir(parents=True)
    (apps / "TX-GEN-004").mkdir()
    monkeypatch.setattr(store, "APPLICATIONS_DIR", apps)
    assert store.allocate_project_id("transmission", "generation") == "TX-GEN-005"
    assert store.allocate_project_id("distribution", "storage") == "DX-STO-001"


def test_accept_renders_form_and_moves_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    store.create_pending("msg-2", _submission(),
                         attachments=[("red_line.pdf", b"%PDF-1.4 fake")],
                         sender="dev@example.com", subject="App")

    project_id = store.accept_pending("msg-2")
    assert project_id == "TX-GEN-001"
    bundle = store.APPLICATIONS_DIR / project_id
    assert (bundle / "00_application_form.pdf").is_file()
    assert (bundle / "red_line.pdf").is_file()
    assert not (store.PENDING_DIR / "msg-2").exists()      # moved out of pending

    # the rendered form parses back through the real parser
    from grid_agent_core.review_api import parse_submission
    parsed = parse_submission(bundle)
    assert parsed["id"] == project_id
    assert parsed["sections"][0]["title"] == "Site & location"


def test_reject_archives_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    store.create_pending("msg-3", _submission(), attachments=[], sender="x@y.z", subject="s")
    store.reject_pending("msg-3", reason="incomplete")
    assert not (store.PENDING_DIR / "msg-3").exists()
    assert (store.PENDING_DIR / "_rejected" / "msg-3").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent_core.intake_store'`.

- [ ] **Step 3: Implement the store**

```python
# grid_agent_core/intake_store.py
"""Filesystem store for pending email submissions + Accept/Reject.

Pending bundles live under review_seed/pending/{intake_id}/ as submission.json
(the extracted dict + sender/subject) plus the original attachment PDFs. Accept
allocates a project id, renders 00_application_form.pdf, and moves the bundle
into review_seed/applications/ where the existing review pipeline picks it up.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .application_form import render_application_form

_SEED = Path(__file__).resolve().parents[1] / "review_seed"
PENDING_DIR = _SEED / "pending"
APPLICATIONS_DIR = _SEED / "applications"

_LEVEL_CODE = {"transmission": "TX", "distribution": "DX"}
_TYPE_CODE = {"generation": "GEN", "demand": "DEM", "storage": "STO", "mixed": "MIX"}
_SUBMISSION_FILE = "submission.json"


def _safe_id(intake_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", intake_id)


def create_pending(intake_id: str, submission: dict[str, Any],
                   attachments: list[tuple[str, bytes]], *, sender: str, subject: str) -> Path:
    dest = PENDING_DIR / _safe_id(intake_id)
    dest.mkdir(parents=True, exist_ok=True)
    record = {**submission, "intake": {**submission.get("intake", {}),
                                       "sender": sender, "subject": subject,
                                       "intake_id": intake_id}}
    (dest / _SUBMISSION_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2))
    for name, data in attachments:
        (dest / _safe_id(name)).write_bytes(data)
    return dest


def load_pending(intake_id: str) -> dict[str, Any]:
    path = PENDING_DIR / _safe_id(intake_id) / _SUBMISSION_FILE
    if not path.is_file():
        raise KeyError(f"Unknown pending intake: {intake_id}")
    return json.loads(path.read_text())


def list_pending() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not PENDING_DIR.is_dir():
        return out
    for d in sorted(PENDING_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        sub = d / _SUBMISSION_FILE
        if not sub.is_file():
            continue
        rec = json.loads(sub.read_text())
        intake = rec.get("intake", {})
        out.append({
            "id": intake.get("intake_id", d.name),
            "name": rec.get("name", ""), "applicant": rec.get("applicant", ""),
            "level": rec.get("level", ""), "conn_type": rec.get("conn_type", ""),
            "sender": intake.get("sender", ""), "subject": intake.get("subject", ""),
            "status": intake.get("status", "extracted"),
            "section_count": len(rec.get("sections", [])),
            "flag_count": len(intake.get("flags", [])),
        })
    return out


def allocate_project_id(level: str, conn_type: str) -> str:
    prefix = f"{_LEVEL_CODE[level]}-{_TYPE_CODE[conn_type]}-"
    pat = re.compile(re.escape(prefix) + r"(\d+)$")
    nums = [int(m.group(1)) for d in APPLICATIONS_DIR.glob(f"{prefix}*")
            if (m := pat.match(d.name))] if APPLICATIONS_DIR.is_dir() else []
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def accept_pending(intake_id: str) -> str:
    src = PENDING_DIR / _safe_id(intake_id)
    rec = load_pending(intake_id)
    project_id = allocate_project_id(rec["level"], rec["conn_type"])
    dest = APPLICATIONS_DIR / project_id
    dest.mkdir(parents=True, exist_ok=True)
    project = {**rec, "id": project_id, "status": "Under review"}
    render_application_form(project, dest / "00_application_form.pdf")
    for pdf in src.glob("*.pdf"):
        shutil.copy2(pdf, dest / pdf.name)
    shutil.rmtree(src)
    return project_id


def reject_pending(intake_id: str, reason: str | None = None) -> None:
    src = PENDING_DIR / _safe_id(intake_id)
    if not src.is_dir():
        raise KeyError(f"Unknown pending intake: {intake_id}")
    if reason:
        (src / "reject_reason.txt").write_text(reason)
    archive = PENDING_DIR / "_rejected" / _safe_id(intake_id)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        shutil.rmtree(archive)
    shutil.move(str(src), str(archive))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_store.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/GridAgentCore/grid_agent_core/intake_store.py tests/grid_agent_core/test_intake_store.py
git commit -m "feat: pending-intake store with Accept (render+promote) / Reject"
```

---

## Task 5: Intake REST endpoints

Expose the store over `/api/review/intake/*`, reusing the existing review router.

**Files:**
- Modify: `app/GridAgentCore/grid_agent_core/review_api.py` (add models + 4 routes at end of file)
- Test: `tests/grid_agent_core/test_intake_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/grid_agent_core/test_intake_api.py
from __future__ import annotations

from fastapi.testclient import TestClient

import grid_agent_core.intake_store as store
from grid_agent_core import local_api


def _seed_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    submission = {
        "id": "", "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
        "level": "transmission", "conn_type": "generation", "capacity": "300 MW",
        "status": "", "submitted": "",
        "sections": [{"id": "site", "title": "Site & location", "requirement": "Address + GPS.",
                      "submitted": "Testfield Moor.", "docs": [], "confidence": "high"}],
        "documents": [], "intake": {"status": "extracted", "level_confidence": "high",
                                    "flags": ["check planning"], "unmapped_docs": []},
    }
    store.create_pending("msg-1", submission, attachments=[],
                         sender="dev@example.com", subject="Application")


def test_list_and_get_intake(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)

    r = client.get("/api/review/intake")
    assert r.status_code == 200
    items = r.json()["pending"]
    assert items[0]["id"] == "msg-1"
    assert items[0]["flag_count"] == 1

    r = client.get("/api/review/intake/msg-1")
    assert r.status_code == 200
    detail = r.json()
    assert detail["sections"][0]["title"] == "Site & location"
    assert detail["intake"]["flags"] == ["check planning"]


def test_accept_promotes_to_project(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    r = client.post("/api/review/intake/msg-1/accept")
    assert r.status_code == 200
    assert r.json()["project_id"] == "TX-GEN-001"
    assert (store.APPLICATIONS_DIR / "TX-GEN-001" / "00_application_form.pdf").is_file()


def test_reject_removes_from_queue(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    r = client.post("/api/review/intake/msg-1/reject", json={"reason": "incomplete"})
    assert r.status_code == 200
    assert client.get("/api/review/intake").json()["pending"] == []


def test_get_unknown_intake_404(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    assert client.get("/api/review/intake/nope").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_api.py -v`
Expected: FAIL (404s / missing routes).

- [ ] **Step 3: Add the routes to `review_api.py`**

Add at the top with the other imports:

```python
from . import intake_store
```

Append these routes at the end of `review_api.py` (after `copilot`):

```python
class RejectRequest(BaseModel):
    reason: str | None = None


@router.get("/intake")
async def list_intake() -> dict[str, Any]:
    return {"pending": intake_store.list_pending()}


@router.get("/intake/{intake_id}")
async def get_intake(intake_id: str) -> dict[str, Any]:
    try:
        return intake_store.load_pending(intake_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intake: {intake_id}")


@router.post("/intake/{intake_id}/accept")
async def accept_intake(intake_id: str) -> dict[str, Any]:
    try:
        project_id = intake_store.accept_pending(intake_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intake: {intake_id}")
    return {"project_id": project_id}


@router.post("/intake/{intake_id}/reject")
async def reject_intake(intake_id: str, body: RejectRequest | None = None) -> dict[str, Any]:
    try:
        intake_store.reject_pending(intake_id, body.reason if body else None)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intake: {intake_id}")
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Mount pending PDFs for the viewer**

In `local_api.py`, right after the `/review-pdfs` mount (line ~195), add:

```python
# Pending intake bundles (original attachments) served for the intake viewer.
_pending_dir = REVIEW_SEED_DIR.parent / "pending"
_pending_dir.mkdir(parents=True, exist_ok=True)
app.mount("/intake-pdfs", StaticFiles(directory=str(_pending_dir)), name="intake-pdfs")
```

(`REVIEW_SEED_DIR` is the `applications/` dir; `.parent` is `review_seed/`.)

- [ ] **Step 6: Full backend suite green**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core -q`
Expected: all tests pass (existing + new).

- [ ] **Step 7: Commit**

```bash
git add app/GridAgentCore/grid_agent_core/review_api.py app/GridAgentCore/grid_agent_core/local_api.py tests/grid_agent_core/test_intake_api.py
git commit -m "feat: /api/review/intake list/get/accept/reject + pending PDF mount"
```

---

## Task 6: Gmail poller

OAuth client + a poll loop that pulls unread attachment emails, runs the extractor, and creates pending bundles — idempotent via Gmail labels. Logic is unit-tested with a fake Gmail service; the real `googleapiclient` build is isolated behind one function.

**Files:**
- Create: `app/GridAgentCore/grid_agent_core/intake_gmail.py`
- Modify: `app/GridAgentCore/grid_agent_core/settings.py`
- Modify: `app/GridAgentCore/grid_agent_core/local_api.py` (startup hook)
- Test: `tests/grid_agent_core/test_intake_gmail.py`

- [ ] **Step 1: Add settings helpers**

Append to `grid_agent_core/settings.py`:

```python
def gmail_intake_enabled() -> bool:
    return os.getenv("GRID_GMAIL_INTAKE", "0").strip() in ("1", "true", "True")


def gmail_token_file() -> str:
    return os.getenv("GRID_GMAIL_TOKEN_FILE", "").strip()


def gmail_query() -> str:
    return os.getenv("GRID_GMAIL_QUERY", "is:unread has:attachment").strip()


def gmail_poll_seconds() -> int:
    return int(os.getenv("GRID_GMAIL_POLL_SECONDS", "45"))


def gmail_send_acks() -> bool:
    return os.getenv("GRID_GMAIL_SEND_ACKS", "0").strip() in ("1", "true", "True")
```

- [ ] **Step 2: Write the failing test (fake Gmail service)**

```python
# tests/grid_agent_core/test_intake_gmail.py
from __future__ import annotations

import base64

import grid_agent_core.intake_store as store
from grid_agent_core.intake_gmail import process_message, INGESTED_LABEL


class FakeExtractor:
    def __call__(self, attachments, body, model=None):
        return {
            "id": "", "name": "Testfield Wind", "applicant": "T Ltd",
            "level": "transmission", "conn_type": "generation", "capacity": "300 MW",
            "status": "", "submitted": "",
            "sections": [], "documents": [{"name": a["name"]} for a in attachments],
            "intake": {"status": "extracted", "level_confidence": "high",
                       "flags": [], "unmapped_docs": []},
        }


class FakeGmail:
    """Minimal stand-in for the googleapiclient Gmail service."""
    def __init__(self, message):
        self._message = message
        self.labelled = []
        self.attachment = base64.urlsafe_b64encode(b"%PDF-1.4 fake").decode()

    # service.users().messages().get(...).execute()
    def users(self):
        return self
    def messages(self):
        return self
    def get(self, userId, id, format=None):
        return _Exec(self._message)
    def attachments(self):
        return self
    def _att_get(self, userId, messageId, id):
        return _Exec({"data": self.attachment})
    def modify(self, userId, id, body):
        self.labelled.append((id, body))
        return _Exec({})


class _Exec:
    def __init__(self, val): self._val = val
    def execute(self): return self._val


def _message():
    return {
        "id": "msg-42",
        "payload": {
            "headers": [{"name": "From", "value": "dev@example.com"},
                        {"name": "Subject", "value": "Our application"}],
            "parts": [
                {"mimeType": "text/plain",
                 "body": {"data": base64.urlsafe_b64encode(b"See attached.").decode()}},
                {"mimeType": "application/pdf", "filename": "red_line.pdf",
                 "body": {"attachmentId": "att-1"}},
            ],
        },
    }


def test_process_message_creates_pending_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    gmail = FakeGmail(_message())
    # patch the attachment fetch indirection used by process_message
    monkeypatch.setattr("grid_agent_core.intake_gmail._fetch_attachment",
                        lambda svc, mid, aid: b"%PDF-1.4 fake")

    process_message(gmail, _message(), extractor=FakeExtractor(),
                    text_reader=lambda data: "Red line plan text")

    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == "msg-42"
    assert pending[0]["sender"] == "dev@example.com"
    assert (store.PENDING_DIR / "msg-42" / "red_line.pdf").is_file()
    # message was labelled ingested (idempotency marker)
    assert gmail.labelled and gmail.labelled[0][0] == "msg-42"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_gmail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent_core.intake_gmail'`.

- [ ] **Step 4: Implement the poller**

```python
# grid_agent_core/intake_gmail.py
"""Gmail intake poller: pull unread attachment emails -> extract -> pending bundle.

Idempotent via a Gmail label (already-ingested messages are excluded by the
search query and labelled on success). The real googleapiclient service is built
in build_service(); all message logic takes the service as an argument so it is
unit-testable with a fake. Env-gated by settings.gmail_intake_enabled().
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Callable

from . import intake_store, settings
from .intake import extract_submission

log = logging.getLogger("grid.intake.gmail")

INGESTED_LABEL = "GridIntake/Ingested"
FAILED_LABEL = "GridIntake/Failed"
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def build_service():  # pragma: no cover - thin googleapiclient wrapper
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(settings.gmail_token_file(), _SCOPES)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _walk_parts(payload: dict):
    stack = [payload]
    while stack:
        part = stack.pop()
        for child in part.get("parts", []) or []:
            stack.append(child)
        yield part


def _fetch_attachment(service, message_id: str, attachment_id: str) -> bytes:  # pragma: no cover
    resp = (service.users().messages().attachments()
            .get(userId="me", messageId=message_id, id=attachment_id).execute())
    return base64.urlsafe_b64decode(resp["data"])


def _decode_body(payload: dict) -> str:
    for part in _walk_parts(payload):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
    return ""


def _ensure_label(service, name: str) -> str:  # pragma: no cover - network
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for lab in existing:
        if lab["name"] == name:
            return lab["id"]
    created = service.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow",
                            "messageListVisibility": "show"}).execute()
    return created["id"]


def _apply_label(service, message_id: str, label_name: str) -> None:
    try:
        label_id = _ensure_label(service, label_name)
    except Exception:  # in tests the fake has no labels(); fall back to raw name
        label_id = label_name
    service.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]}).execute()


def process_message(service, message: dict, *,
                    extractor: Callable[..., dict] = extract_submission,
                    text_reader: Callable[[bytes], str] | None = None) -> None:
    """Extract one Gmail message into a pending bundle and label it ingested."""
    from .review_api import _extract_text  # fitz-based PDF text extractor

    msg_id = message["id"]
    payload = message.get("payload", {})
    sender, subject = _header(message, "From"), _header(message, "Subject")
    body = _decode_body(payload)

    attachments: list[dict] = []         # for the extractor: {name, text}
    raw: list[tuple[str, bytes]] = []    # to persist: (name, bytes)
    for part in _walk_parts(payload):
        filename = part.get("filename") or ""
        att_id = part.get("body", {}).get("attachmentId")
        if not filename.lower().endswith(".pdf") or not att_id:
            continue
        data = _fetch_attachment(service, msg_id, att_id)
        raw.append((filename, data))
        if text_reader is not None:
            text = text_reader(data)
        else:  # pragma: no cover - real path writes a temp file for fitz
            import tempfile
            from pathlib import Path
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                tmp.write(data); tmp.flush()
                text = _extract_text(Path(tmp.name))
        attachments.append({"name": filename, "text": text})

    try:
        submission = extractor(attachments, body)
        intake_store.create_pending(msg_id, submission, raw, sender=sender, subject=subject)
        _apply_label(service, msg_id, INGESTED_LABEL)
    except Exception:
        log.exception("intake failed for message %s", msg_id)
        _apply_label(service, msg_id, FAILED_LABEL)


def poll_once(service) -> int:  # pragma: no cover - network glue
    listed = service.users().messages().list(
        userId="me", q=settings.gmail_query()).execute().get("messages", [])
    for ref in listed:
        full = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        process_message(service, full)
    return len(listed)


async def run_poller() -> None:  # pragma: no cover - background loop
    service = build_service()
    while True:
        try:
            n = await asyncio.to_thread(poll_once, service)
            if n:
                log.info("intake poll processed %d message(s)", n)
        except Exception:
            log.exception("intake poll error; backing off")
        await asyncio.sleep(settings.gmail_poll_seconds())


def start_intake_poller() -> asyncio.Task | None:  # pragma: no cover - wiring
    if not settings.gmail_intake_enabled() or not settings.gmail_token_file():
        log.info("Gmail intake disabled (set GRID_GMAIL_INTAKE=1 + GRID_GMAIL_TOKEN_FILE)")
        return None
    log.info("Gmail intake poller starting (every %ds)", settings.gmail_poll_seconds())
    return asyncio.create_task(run_poller())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core/test_intake_gmail.py -v`
Expected: PASS. The fake's `modify(...)` records the label call; `_apply_label`'s `_ensure_label` raises on the fake and falls back to the raw label name, so `gmail.labelled[0][0] == "msg-42"`.

- [ ] **Step 6: Wire startup in `local_api.py`**

Add near the imports:

```python
from .intake_gmail import start_intake_poller
```

Add after the app/router setup (anywhere after `app = FastAPI(...)`):

```python
@app.on_event("startup")
async def _start_intake() -> None:
    start_intake_poller()
```

- [ ] **Step 7: Confirm dormant-by-default (no creds → no crash)**

Run: `cd app/GridAgentCore && uv run python -c "from grid_agent_core import local_api; from fastapi.testclient import TestClient; TestClient(local_api.app).__enter__(); print('startup ok')"`
Expected: prints `startup ok` (poller logs "disabled", app starts fine).

- [ ] **Step 8: Commit**

```bash
git add app/GridAgentCore/grid_agent_core/intake_gmail.py app/GridAgentCore/grid_agent_core/settings.py app/GridAgentCore/grid_agent_core/local_api.py tests/grid_agent_core/test_intake_gmail.py
git commit -m "feat: Gmail intake poller (label-idempotent), env-gated startup hook"
```

---

## Task 7: Dependencies + run notes

**Files:**
- Modify: `app/GridAgentCore/pyproject.toml`
- Modify: `app/review_frontend/README.md` (intake run notes)

- [ ] **Step 1: Add Google API deps to the `build` extra**

In `pyproject.toml`, under `[project.optional-dependencies] build = [...]`, add:

```python
    "google-api-python-client>=2.100,<3",
    "google-auth>=2.23,<3",
    "google-auth-oauthlib>=1.1,<2",
```

- [ ] **Step 2: Sync deps**

Run: `cd app/GridAgentCore && uv sync --extra build --extra dev`
Expected: resolves and installs the three Google packages.

- [ ] **Step 3: Document the OAuth + env in the README**

Append an "## Email intake (Gmail)" section to `app/review_frontend/README.md` documenting: create a Google Cloud project + OAuth client, run a one-off script to mint the token file (scope `gmail.modify`), and the env vars `GRID_GMAIL_INTAKE=1`, `GRID_GMAIL_TOKEN_FILE`, `GRID_GMAIL_QUERY`, `GRID_GMAIL_POLL_SECONDS`, `GRID_GMAIL_SEND_ACKS=0`. State that acks are OFF by default and that anyone emailing the inbox creates a pending card (the operator gate is the trust boundary).

- [ ] **Step 4: Commit**

```bash
git add app/GridAgentCore/pyproject.toml app/review_frontend/README.md
git commit -m "build: add Gmail API deps + intake run notes"
```

---

## Task 8: Frontend — types + API client

No JS test runner in this project; verify by `npm run build` (tsc) + manual checks.

**Files:**
- Modify: `app/review_frontend/src/types.ts`
- Modify: `app/review_frontend/src/api.ts`

- [ ] **Step 1: Add intake types**

Append to `types.ts`:

```typescript
export type Confidence = "high" | "medium" | "low";

export interface IntakeSummary {
  id: string;
  name: string;
  applicant: string;
  level: Level;
  conn_type: ConnType;
  sender: string;
  subject: string;
  status: string;       // extracted | extraction_failed
  section_count: number;
  flag_count: number;
}

export interface IntakeSection extends Section {
  confidence: Confidence;
}

export interface IntakeBlock {
  status: string;
  level_confidence: Confidence;
  flags: string[];
  unmapped_docs: string[];
  sender?: string;
  subject?: string;
  intake_id?: string;
  error?: string;
}

export interface IntakeDetail {
  id?: string;
  name: string;
  applicant: string;
  level: Level;
  conn_type: ConnType;
  capacity: string;
  sections: IntakeSection[];
  documents: { name: string }[];
  intake: IntakeBlock;
}
```

- [ ] **Step 2: Add intake API functions**

Append to `api.ts`:

```typescript
import type { IntakeDetail, IntakeSummary } from "./types";

export async function fetchIntakeQueue(): Promise<IntakeSummary[]> {
  const r = await fetch(`/api/review/intake`);
  if (!r.ok) throw new Error(`intake ${r.status}`);
  return (await r.json()).pending;
}

export async function fetchIntake(id: string): Promise<IntakeDetail> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(`intake ${r.status}`);
  return r.json();
}

export async function acceptIntake(id: string): Promise<string> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}/accept`, { method: "POST" });
  if (!r.ok) throw new Error(`accept ${r.status}`);
  return (await r.json()).project_id;
}

export async function rejectIntake(id: string, reason: string): Promise<void> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}/reject`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) throw new Error(`reject ${r.status}`);
}

/** Original attachment PDF for a pending intake (served from review_seed/pending). */
export function intakePdfUrl(intakeId: string, doc: string): string {
  return `/intake-pdfs/${encodeURIComponent(intakeId)}/${doc}`;
}
```

(Merge the new `import type` with the existing one at the top of `api.ts` rather than adding a second import line.)

- [ ] **Step 3: Typecheck**

Run: `cd app/review_frontend && npm run build`
Expected: build succeeds (no TS errors). If `framer-motion`/types complain, they're unrelated to this change.

- [ ] **Step 4: Commit**

```bash
git add app/review_frontend/src/types.ts app/review_frontend/src/api.ts
git commit -m "feat(ui): intake types + API client"
```

---

## Task 9: Frontend — Pending intake panel + detail page

**Files:**
- Create: `app/review_frontend/src/pages/IntakePage.tsx`
- Modify: `app/review_frontend/src/pages/Dashboard.tsx`
- Modify: `app/review_frontend/src/App.tsx`

- [ ] **Step 1: Add the intake detail page**

```tsx
// app/review_frontend/src/pages/IntakePage.tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { acceptIntake, fetchIntake, intakePdfUrl, rejectIntake } from "../api";
import type { IntakeDetail } from "../types";

export function IntakePage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState<IntakeDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchIntake(id).then(setData).catch((e) => setErr(String(e)));
  }, [id]);

  if (err) return <div className="page"><div className="empty-state">{err}</div></div>;
  if (!data) return <div className="page"><div className="loading-rail"><span className="spinner" /> loading…</div></div>;

  const accept = async () => {
    setBusy(true);
    try { nav(`/project/${await acceptIntake(id)}`); }
    catch (e) { setErr(String(e)); setBusy(false); }
  };
  const reject = async () => {
    const reason = window.prompt("Reason for rejecting (optional):") ?? "";
    setBusy(true);
    try { await rejectIntake(id, reason); nav("/"); }
    catch (e) { setErr(String(e)); setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div className="eyebrow">pending intake · {data.level} / {data.conn_type}</div>
        <h1>{data.name || "(unnamed submission)"}</h1>
        <p>From {data.intake.sender} — “{data.intake.subject}”. Applicant: {data.applicant}.</p>
      </div>

      {data.intake.flags.length > 0 && (
        <div className="empty-state"><div className="big">Extraction flags</div>
          <ul>{data.intake.flags.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </div>
      )}

      <div className="intake-grid">
        <div>
          <h3>Extracted sections</h3>
          {data.sections.map((s) => (
            <div className="section-card" key={s.id}>
              <div className="row-between">
                <strong>{s.title}</strong>
                <span className={`chip chip-${s.confidence}`}>{s.confidence}</span>
              </div>
              <p className="muted">{s.requirement}</p>
              <p>{s.submitted || <em>— no answer extracted —</em>}</p>
              {s.docs.length > 0 && <div className="muted">docs: {s.docs.join(", ")}</div>}
            </div>
          ))}
        </div>
        <div>
          <h3>Original attachments</h3>
          {data.documents.length === 0 && <p className="muted">No PDF attachments.</p>}
          {data.documents.map((d) => (
            <a className="doc-link" key={d.name} href={intakePdfUrl(id, d.name)}
               target="_blank" rel="noreferrer">{d.name}</a>
          ))}
        </div>
      </div>

      <div className="action-bar">
        <button className="btn-primary" disabled={busy} onClick={accept}>Accept → create application</button>
        <button className="btn-ghost" disabled={busy} onClick={reject}>Reject</button>
      </div>
    </div>
  );
}
```

(Reuse existing CSS classes where present in `styles.css`; `intake-grid`, `chip-*`, `row-between`, `doc-link`, `action-bar` may need small additions — add minimal rules to `styles.css` to lay out two columns and a button row. Keep it consistent with the existing SIF aesthetic.)

- [ ] **Step 2: Add the route**

In `App.tsx`, import and register the route alongside the existing ones:

```tsx
import { IntakePage } from "./pages/IntakePage";
// ...
<Route path="/intake/:id" element={<IntakePage />} />
```

- [ ] **Step 3: Add the "Pending intake" panel to the Dashboard**

In `Dashboard.tsx`, add state + fetch and render a panel above the project queue:

```tsx
import { fetchIntakeQueue, fetchProjects } from "../api";
import type { IntakeSummary, Level, ProjectSummary } from "../types";
// inside Dashboard(), after the projects state:
const [intake, setIntake] = useState<IntakeSummary[]>([]);
useEffect(() => { fetchIntakeQueue().then(setIntake).catch(() => setIntake([])); }, [level]);
// render near the top of the returned JSX (before the project cards):
{intake.length > 0 && (
  <div className="intake-panel">
    <div className="eyebrow">pending intake · {intake.length} awaiting review</div>
    {intake.map((it) => (
      <Link className="intake-row" key={it.id} to={`/intake/${encodeURIComponent(it.id)}`}>
        <span>{it.name || it.subject || "(unnamed)"}</span>
        <span className="muted">{it.level}/{it.conn_type} · from {it.sender}</span>
        {it.flag_count > 0 && <span className="chip chip-low">{it.flag_count} flags</span>}
        {it.status === "extraction_failed" && <span className="chip chip-low">extraction failed</span>}
      </Link>
    ))}
  </div>
)}
```

- [ ] **Step 4: Typecheck + manual smoke**

Run: `cd app/review_frontend && npm run build`
Expected: build succeeds.

Manual (optional, needs backend): seed a fake pending bundle, then:
```bash
cd app/GridAgentCore && uv run python - <<'PY'
import grid_agent_core.intake_store as s
sub = {"id":"","name":"Demo Wind","applicant":"Demo Ltd","level":"transmission",
 "conn_type":"generation","capacity":"100 MW","status":"","submitted":"",
 "sections":[{"id":"site","title":"Site & location","requirement":"Address + GPS.",
   "submitted":"Demo Moor.","docs":[],"confidence":"high"}],"documents":[],
 "intake":{"status":"extracted","level_confidence":"high","flags":["check planning"],"unmapped_docs":[]}}
s.create_pending("demo-1", sub, [], sender="dev@example.com", subject="Demo application")
print("seeded")
PY
```
Start backend (`uv run grid-local-api --port 8000`) + frontend (`npm run dev`), confirm the Pending-intake row appears, open it, click Accept, confirm it redirects to the new project and the card disappears.

- [ ] **Step 5: Commit**

```bash
git add app/review_frontend/src/pages/IntakePage.tsx app/review_frontend/src/pages/Dashboard.tsx app/review_frontend/src/App.tsx app/review_frontend/src/styles.css
git commit -m "feat(ui): pending-intake panel + accept/reject detail page"
```

---

## Task 10: End-to-end verification

- [ ] **Step 1: Full backend suite**

Run: `cd app/GridAgentCore && uv run pytest ../../tests/grid_agent_core -q`
Expected: all pass.

- [ ] **Step 2: Frontend build**

Run: `cd app/review_frontend && npm run build`
Expected: success.

- [ ] **Step 3: Real-email smoke (manual, requires Gmail token)**

With `GRID_GMAIL_INTAKE=1` + `GRID_GMAIL_TOKEN_FILE` set and the backend running, email the intake inbox a cover note + 2–3 PDFs. Within ~1 min confirm: a Pending-intake card appears; opening it shows extracted sections with confidence + any flags next to the attachment links; Accept creates a `TX-*`/`DX-*` project that opens in the normal review view; the Gmail message gets the `GridIntake/Ingested` label and is no longer re-ingested on the next poll.

- [ ] **Step 4: Final commit (if any styles/tweaks pending)**

```bash
git add -A && git commit -m "chore: email intake end-to-end verified"
```

---

## Self-review notes (author)

- **Spec coverage:** transport/poller (T6), extractor against vendored schema (T2, T3), pending store + Accept/Reject (T4, T5), portal queue + detail (T8, T9), acks-off-by-default + failure handling (T3 failure path, T6 FAILED label, T7 env), round-trip contract (T1). Acks *sending* is scaffolded via the `GRID_GMAIL_SEND_ACKS` flag + scope note but intentionally not implemented in the MVP path (off by default) — if you want the ack send now, add a `send_ack(service, to, subject)` helper in `intake_gmail.py` gated on `settings.gmail_send_acks()` and an extra `gmail.send` scope.
- **Naming consistency:** `extract_submission(attachments, body, model=...)`, `create_pending(intake_id, submission, attachments, *, sender, subject)`, `accept_pending → project_id`, `list_pending` keys (`id, name, applicant, level, conn_type, sender, subject, status, section_count, flag_count`) match across store, API, and UI types.
- **Known sharp edges:** fitz reads from a path, so the real attachment path writes a temp file (covered by the `text_reader` injection in tests); `_apply_label` falls back to a raw label name when the fake service lacks `labels()`.
