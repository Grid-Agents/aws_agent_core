"""Application Review API.

Operator-facing endpoints for the Grid Application Review MVP. A developer
submission is a *bundle* of PDFs under ``review_seed/applications/{PROJECT_ID}/``
(an application form plus supporting documents). This router parses those PDFs
back into structured sections on demand and wraps the existing Grid agent
(`run_grid_agent_events`) to:

  * review one application section against the regulatory corpus, checking the
    developer's claim and its supporting documents (`/sections/{sid}/review`); and
  * answer an operator's ad-hoc question about a highlighted span (`/copilot`).

Both review endpoints stream the same NDJSON trace/result events the `/api/grid/run`
console already renders, and honour the deployed-runtime switch
(`AGENTCORE_RUNTIME_ARN`) so the demo can run against the real AWS indexes.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import run_grid_agent_events

router = APIRouter(prefix="/api/review", tags=["review"])

# review_seed/applications lives next to the grid_agent_core package.
SEED_DIR = Path(__file__).resolve().parents[1] / "review_seed" / "applications"
SEED_DIR.mkdir(parents=True, exist_ok=True)

FORM_FILENAME = "00_application_form.pdf"
DEFAULT_METHODS = ["vector", "pageindex", "find"]
_MAX_DOC_CHARS = 6000  # cap per supporting document injected into a review prompt


# --------------------------------------------------------------------------- #
# PDF parsing: bundle -> structured submission
# --------------------------------------------------------------------------- #

_META_LABELS = [
    "PROJECT ID", "PROJECT NAME", "APPLICANT", "LEVEL",
    "CONNECTION TYPE", "CAPACITY", "STATUS", "DATE SUBMITTED",
]
_SECTION_RE = re.compile(r"^SECTION\s+(\d+):\s*(.*)$")
_FIELD_LABELS = {
    "REQUIREMENT:": "requirement",
    "SUBMITTED:": "submitted",
    "SUPPORTING DOCS:": "docs_raw",
}

# Parsed bundles are cached, keyed by project id and invalidated when any PDF in
# the bundle changes (latest mtime).
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _extract_text(pdf_path: Path) -> str:
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def _bundle_mtime(bundle: Path) -> float:
    return max((p.stat().st_mtime for p in bundle.glob("*.pdf")), default=0.0)


def parse_submission(bundle: Path) -> dict[str, Any]:
    """Parse a bundle folder into project metadata, sections, and documents."""
    text = _extract_text(bundle / FORM_FILENAME)
    meta: dict[str, str] = {}
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    field: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        sec_match = _SECTION_RE.match(line)
        if sec_match:
            current = {
                "id": f"s{sec_match.group(1)}",
                "title": sec_match.group(2).strip(),
                "requirement": "",
                "submitted": "",
                "docs_raw": "",
            }
            sections.append(current)
            field = None
            continue

        if line in _FIELD_LABELS and current is not None:
            field = _FIELD_LABELS[line]
            continue

        meta_label = next((lbl for lbl in _META_LABELS if line.startswith(lbl + ":")), None)
        if meta_label:
            meta[meta_label] = line[len(meta_label) + 1:].strip()
            field = None
            continue

        # Continuation line for the active section field.
        if current is not None and field is not None:
            existing = current[field]
            current[field] = f"{existing} {line}".strip() if existing else line

    for sec in sections:
        raw_docs = sec.pop("docs_raw", "").strip()
        sec["docs"] = (
            [] if raw_docs.lower() in ("", "none")
            else [d.strip() for d in raw_docs.split(",") if d.strip()]
        )

    documents = [
        {"name": pdf.name, "text": _extract_text(pdf)}
        for pdf in sorted(bundle.glob("*.pdf"))
        if pdf.name != FORM_FILENAME
    ]

    return {
        "id": meta.get("PROJECT ID", bundle.name),
        "name": meta.get("PROJECT NAME", bundle.name),
        "applicant": meta.get("APPLICANT", ""),
        "level": meta.get("LEVEL", "").lower(),
        "conn_type": meta.get("CONNECTION TYPE", ""),
        "capacity": meta.get("CAPACITY", ""),
        "status": meta.get("STATUS", ""),
        "submitted": meta.get("DATE SUBMITTED", ""),
        "sections": sections,
        "documents": documents,
    }


def _load_project(project_id: str) -> dict[str, Any]:
    bundle = SEED_DIR / project_id
    if not (bundle / FORM_FILENAME).is_file():
        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
    mtime = _bundle_mtime(bundle)
    cached = _cache.get(project_id)
    if cached and cached[0] == mtime:
        return cached[1]
    parsed = parse_submission(bundle)
    _cache[project_id] = (mtime, parsed)
    return parsed


def _all_projects() -> list[dict[str, Any]]:
    projects = []
    for bundle in sorted(SEED_DIR.iterdir()):
        if bundle.is_dir() and (bundle / FORM_FILENAME).is_file():
            projects.append(_load_project(bundle.name))
    return projects


def _summary(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project["id"],
        "name": project["name"],
        "applicant": project["applicant"],
        "level": project["level"],
        "conn_type": project["conn_type"],
        "capacity": project["capacity"],
        "status": project["status"],
        "submitted": project["submitted"],
        "section_count": len(project["sections"]),
        "document_count": len(project["documents"]),
    }


def _detail(project: dict[str, Any]) -> dict[str, Any]:
    return {
        **_summary(project),
        "sections": [
            {"id": s["id"], "title": s["title"], "requirement": s["requirement"],
             "submitted": s["submitted"], "docs": s["docs"]}
            for s in project["sections"]
        ],
        "documents": [{"name": d["name"]} for d in project["documents"]],
    }


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

def _supporting_text(project: dict[str, Any], section: dict[str, Any]) -> str:
    by_name = {d["name"]: d["text"] for d in project["documents"]}
    parts = []
    for name in section["docs"]:
        body = by_name.get(name)
        if body:
            parts.append(f"--- {name} ---\n{body.strip()[:_MAX_DOC_CHARS]}")
    return "\n\n".join(parts) if parts else "(no supporting documents were attached to this section)"


def _review_prompt(project: dict[str, Any], section: dict[str, Any]) -> str:
    return (
        "You are an expert grid connection engineer reviewing a UK grid interconnection "
        "application on behalf of the network operator.\n\n"
        f"Project: {project['name']} ({project['level']} / {project['conn_type']}, "
        f"{project['capacity']}).\n"
        f"Section under review: {section['title']}\n\n"
        f"REQUIREMENT (what the application must satisfy):\n{section['requirement']}\n\n"
        f"DEVELOPER'S SUBMITTED ANSWER:\n{section['submitted']}\n\n"
        "SUPPORTING DOCUMENTS THE DEVELOPER PROVIDED FOR THIS SECTION:\n"
        f"{_supporting_text(project, section)}\n\n"
        "Task: Using the grid regulatory corpus, retrieve and cite the specific clauses "
        "that apply, then assess whether the submitted answer AND its supporting documents "
        "satisfy the requirement. Explicitly check for any contradiction between what the "
        "developer claims and what their own supporting documents actually say. Keep the "
        "review concise and operator-facing.\n\n"
        "End your answer with exactly these two lines:\n"
        "VERDICT: PASS | NEEDS_REVISION | FAIL\n"
        "SUMMARY: <one sentence>"
    )


def _copilot_prompt(project: dict[str, Any], section_title: str | None,
                    selected_text: str, question: str) -> str:
    section_line = f"Section: {section_title}.\n" if section_title else ""
    return (
        "You are assisting a grid connection operator who is reviewing an application "
        f"(project {project['name']}, {project['level']} / {project['conn_type']}).\n"
        f"{section_line}"
        "The operator highlighted the following text from the application:\n"
        f'"""{selected_text.strip()}"""\n\n'
        f"Operator's question: {question.strip()}\n\n"
        "Answer using the grid regulatory corpus, citing specific clauses where relevant."
    )


# --------------------------------------------------------------------------- #
# Agent streaming (local execution or deployed-runtime proxy)
# --------------------------------------------------------------------------- #

async def _stream_agent(payload: dict[str, Any]) -> AsyncIterator[str]:
    # Lazy import avoids a circular import: local_api includes this router.
    from .local_api import _agentcore_event_lines, _agentcore_runtime_arn

    try:
        if _agentcore_runtime_arn():
            yield json.dumps({
                "type": "trace",
                "entry": {
                    "id": 0, "kind": "agentcore",
                    "title": "Invoking deployed AgentCore runtime",
                    "detail": "Forwarding this review to AWS Bedrock AgentCore.",
                    "metadata": {},
                },
            }, ensure_ascii=False) + "\n"
            for line in _agentcore_event_lines(dict(payload)):
                if line:
                    yield line
        else:
            payload.pop("runtime_session_id", None)
            async for event in run_grid_agent_events(payload):
                yield json.dumps(event, ensure_ascii=False) + "\n"
    except Exception as exc:  # surface failures as a terminal result event
        message = f"{type(exc).__name__}: {exc}"
        yield json.dumps({
            "type": "trace",
            "entry": {"id": 0, "kind": "error", "title": "Review invocation failed",
                      "detail": message, "metadata": {}},
        }, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "result", "status": "error", "error": message},
                         ensure_ascii=False) + "\n"


def _ndjson(payload: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(_stream_agent(payload), media_type="application/x-ndjson")


# --------------------------------------------------------------------------- #
# Request models + routes
# --------------------------------------------------------------------------- #

class ReviewOptions(BaseModel):
    methods: list[str] = Field(default_factory=lambda: list(DEFAULT_METHODS))
    enable_subagents: bool = True


class CopilotRequest(BaseModel):
    project_id: str
    section_id: str | None = None
    selected_text: str = Field(min_length=1, max_length=8000)
    question: str = Field(min_length=1, max_length=2000)
    methods: list[str] = Field(default_factory=lambda: list(DEFAULT_METHODS))
    enable_subagents: bool = True


@router.get("/projects")
async def list_projects(level: str | None = None) -> dict[str, Any]:
    projects = _all_projects()
    if level:
        projects = [p for p in projects if p["level"] == level.lower()]
    return {"projects": [_summary(p) for p in projects]}


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return _detail(_load_project(project_id))


@router.post("/projects/{project_id}/sections/{section_id}/review")
async def review_section(
    project_id: str, section_id: str, options: ReviewOptions | None = None
) -> StreamingResponse:
    project = _load_project(project_id)
    section = next((s for s in project["sections"] if s["id"] == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")
    options = options or ReviewOptions()
    return _ndjson({
        "prompt": _review_prompt(project, section),
        "methods": options.methods,
        "enable_subagents": options.enable_subagents,
        "allow_sdk_file_tools": False,
    })


@router.post("/copilot")
async def copilot(request: CopilotRequest) -> StreamingResponse:
    project = _load_project(request.project_id)
    section_title = None
    if request.section_id:
        section = next((s for s in project["sections"] if s["id"] == request.section_id), None)
        section_title = section["title"] if section else None
    return _ndjson({
        "prompt": _copilot_prompt(project, section_title, request.selected_text, request.question),
        "methods": request.methods,
        "enable_subagents": request.enable_subagents,
        "allow_sdk_file_tools": False,
    })
