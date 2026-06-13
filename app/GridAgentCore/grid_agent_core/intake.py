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
