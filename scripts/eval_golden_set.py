#!/usr/bin/env python3
"""Score Grid agent runs against the golden set.

Two modes:
  --run        POST each golden question to the local API and score the results.
  --from-runs  Score existing run-history records (S3) by matching prompts.

Scoring per question:
  retrieval_hit  any retrieved evidence overlaps a golden evidence span
                 (same document AND char-range overlap; page +/-1 fallback).
  citation_hit   same, but restricted to evidence the agent actually cited.
  answer_correct numerical/figure_numerical -> normalized containment of the
                 golden value; otherwise -> LLM judge (Anthropic, haiku).

Usage:
  .venv/bin/python scripts/eval_golden_set.py --golden /tmp/golden_set/golden_set/golden_set.jsonl --run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

API = os.getenv("GRID_EVAL_API", "http://127.0.0.1:8000")
METHODS = ["vector", "pageindex", "find"]
JUDGE_MODEL = os.getenv("GRID_EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s or ""))


def spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def evidence_hit(golden_ev: list[dict], items: list[dict]) -> bool:
    for g in golden_ev:
        for e in items:
            if e.get("document_id") != g.get("document_id"):
                continue
            es, ee = e.get("start_char"), e.get("end_char")
            gs, ge = g.get("char_start"), g.get("char_end")
            if None not in (es, ee, gs, ge) and spans_overlap(es, ee, gs, ge):
                return True
            ep, gp = e.get("page"), g.get("page")
            if ep is not None and gp is not None and abs(int(ep) - int(gp)) <= 1:
                return True
    return False


def judge_answer(question: str, golden: str, answer: str) -> bool:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=10,
        messages=[{
            "role": "user",
            "content": (
                "Grade whether the candidate answer is factually consistent with the "
                "reference answer for this question. Reply with exactly CORRECT or INCORRECT.\n\n"
                f"Question: {question}\n\nReference answer: {golden}\n\nCandidate answer: {answer[:4000]}"
            ),
        }],
    )
    return "CORRECT" in msg.content[0].text.upper()


def score_answer(q: dict, answer: str) -> bool:
    golden = q["answer"]
    if q.get("question_type") in ("numerical", "figure_numerical"):
        gn = _numbers(golden)
        if gn and gn <= _numbers(answer):
            return True
        # fall through to containment for word-numbers ("one voting paper")
        if _norm(golden) in _norm(answer):
            return True
        return judge_answer(q["question"], golden, answer)
    return judge_answer(q["question"], golden, answer)


def run_question(prompt: str, timeout: int = 420) -> dict | None:
    body = json.dumps({
        "prompt": prompt,
        "methods": METHODS,
        "enable_subagents": False,
        "allow_sdk_file_tools": False,
    }).encode()
    req = urllib.request.Request(
        f"{API}/api/grid/run", data=body, headers={"Content-Type": "application/json"}
    )
    final = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                final = ev
    return final


def fetch_runs_index() -> list[dict]:
    with urllib.request.urlopen(f"{API}/api/runs", timeout=30) as r:
        return json.load(r).get("runs", [])


def fetch_run(run_id: str) -> dict:
    with urllib.request.urlopen(f"{API}/api/runs/{run_id}", timeout=60) as r:
        return json.load(r)


def score_result(q: dict, result: dict) -> dict:
    answer = result.get("answer") or ""
    evidence = result.get("evidence") or []
    citations = result.get("citations") or []
    row = {
        "id": q["id"],
        "question_type": q["question_type"],
        "modality": q["modality"],
        "status": result.get("status"),
        "latency_ms": result.get("latency_ms"),
        "retrieved": len(evidence),
        "cited": len(citations),
        "retrieval_hit": evidence_hit(q["evidence"], evidence),
        "citation_hit": evidence_hit(q["evidence"], citations),
        "answer_correct": score_answer(q, answer),
        "answer": answer[:300],
    }
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, required=True)
    ap.add_argument("--run", action="store_true", help="execute questions via the local API")
    ap.add_argument("--from-runs", action="store_true", help="score existing run-history records")
    ap.add_argument("--out", type=Path, default=Path("/tmp/golden_eval"))
    args = ap.parse_args()

    questions = [json.loads(l) for l in args.golden.read_text().splitlines() if l.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []

    if args.from_runs:
        index = fetch_runs_index()
        by_prompt = {}
        for rec in index:  # newest first; keep newest per prompt
            by_prompt.setdefault((rec.get("prompt") or "").strip(), rec["id"])
        for q in questions:
            rid = by_prompt.get(q["question"].strip())
            if not rid:
                print(f"[{q['id']}] NO RUN FOUND — skipped", flush=True)
                continue
            result = fetch_run(rid).get("result", {})
            row = score_result(q, result)
            row["run_id"] = rid
            rows.append(row)
            print(f"[{q['id']}] ans={'Y' if row['answer_correct'] else 'N'} "
                  f"ret={'Y' if row['retrieval_hit'] else 'N'} cit={'Y' if row['citation_hit'] else 'N'}",
                  flush=True)
    elif args.run:
        for q in questions:
            t0 = time.time()
            print(f"[{q['id']}] running…", flush=True)
            try:
                result = run_question(q["question"])
            except Exception as exc:
                print(f"[{q['id']}] RUN FAILED: {exc}", flush=True)
                rows.append({"id": q["id"], "status": "error", "error": str(exc)})
                continue
            if not result:
                rows.append({"id": q["id"], "status": "no-result"})
                continue
            row = score_result(q, result)
            rows.append(row)
            print(f"[{q['id']}] {time.time()-t0:.0f}s ans={'Y' if row['answer_correct'] else 'N'} "
                  f"ret={'Y' if row['retrieval_hit'] else 'N'} cit={'Y' if row['citation_hit'] else 'N'}",
                  flush=True)
    else:
        ap.error("choose --run or --from-runs")

    scored = [r for r in rows if "answer_correct" in r]
    summary = {
        "questions": len(questions),
        "scored": len(scored),
        "answer_accuracy": round(sum(r["answer_correct"] for r in scored) / max(len(scored), 1), 3),
        "retrieval_hit_rate": round(sum(r["retrieval_hit"] for r in scored) / max(len(scored), 1), 3),
        "citation_hit_rate": round(sum(r["citation_hit"] for r in scored) / max(len(scored), 1), 3),
        "by_modality": {},
    }
    for mod in sorted({r["modality"] for r in scored}):
        sub = [r for r in scored if r["modality"] == mod]
        summary["by_modality"][mod] = {
            "n": len(sub),
            "answer_accuracy": round(sum(r["answer_correct"] for r in sub) / len(sub), 3),
        }
    (args.out / "scores.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    lines = ["# Golden-set eval report", "",
             f"- corpus revision: 27 docs (c7dc7b51104d), methods: {', '.join(METHODS)}",
             f"- questions scored: {summary['scored']}/{summary['questions']}",
             f"- **answer accuracy: {summary['answer_accuracy']:.0%}**",
             f"- retrieval hit rate: {summary['retrieval_hit_rate']:.0%}",
             f"- citation hit rate: {summary['citation_hit_rate']:.0%}", "",
             "| id | type | ans | ret | cit | status |", "|---|---|---|---|---|---|"]
    for r in scored:
        lines.append(f"| {r['id']} | {r['question_type']} | "
                     f"{'✅' if r['answer_correct'] else '❌'} | "
                     f"{'✅' if r['retrieval_hit'] else '❌'} | "
                     f"{'✅' if r['citation_hit'] else '❌'} | {r['status']} |")
    for mod, s in summary["by_modality"].items():
        lines.append(f"\n- {mod}: {s['answer_accuracy']:.0%} ({s['n']} q)")
    (args.out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
