from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Iterable
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import run_grid_agent_events
from .artifacts import artifact_revision, configured_s3_uri, ensure_artifacts, runtime_artifact_dir
from .corpus import load_manifest
from .settings import RETRIEVAL_METHODS, model_id


load_dotenv()

app = FastAPI(title="Grid AgentCore Local API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GridRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    methods: list[str] = Field(default_factory=lambda: list(RETRIEVAL_METHODS))
    allow_sdk_file_tools: bool = False
    enable_subagents: bool = True
    runtime_session_id: str | None = None


def _agentcore_runtime_arn() -> str:
    return os.getenv("AGENTCORE_RUNTIME_ARN", "").strip()


def _agentcore_client():
    try:
        import boto3
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise RuntimeError("boto3 is required to invoke deployed AgentCore runtime.") from exc
    return boto3.client("bedrock-agentcore", region_name=os.getenv("AWS_REGION"))


def _agentcore_event_lines(payload: dict[str, Any]) -> Iterable[str]:
    arn = _agentcore_runtime_arn()
    if not arn:
        return []
    runtime_session_id = payload.pop("runtime_session_id", None) or uuid.uuid4().hex
    qualifier = os.getenv("AGENTCORE_RUNTIME_QUALIFIER", "").strip()
    request: dict[str, Any] = {
        "agentRuntimeArn": arn,
        "runtimeSessionId": runtime_session_id,
        "payload": json.dumps(payload).encode("utf-8"),
        "contentType": "application/json",
        "accept": "application/json",
    }
    if qualifier:
        request["qualifier"] = qualifier
    response = _agentcore_client().invoke_agent_runtime(**request)
    content_type = response.get("contentType", "")
    body = response.get("response")
    if body is None:
        return []
    raw_lines = body.iter_lines() if hasattr(body, "iter_lines") else body
    buffered = ""
    for chunk in raw_lines:
        if not chunk:
            continue
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        if "text/event-stream" in content_type and text.startswith("data: "):
            text = text[6:]
        buffered += text
        for line in buffered.splitlines(keepends=True):
            if not line.endswith(("\n", "\r")):
                buffered = line
                break
            yield _normalize_event_line(line.strip())
        else:
            buffered = ""
    if buffered.strip():
        yield _normalize_event_line(buffered.strip())


def _normalize_event_line(line: str) -> str:
    if not line:
        return ""
    try:
        json.loads(line)
        return line + "\n"
    except json.JSONDecodeError:
        return json.dumps({"type": "trace", "entry": {"kind": "agentcore", "detail": line}}) + "\n"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
async def overview() -> dict[str, Any]:
    try:
        root = ensure_artifacts(runtime_artifact_dir())
        records = load_manifest(root)
        ready = {
            "vector": (root / "indexes" / "vector" / "index.json").exists(),
            "pageindex": (root / "indexes" / "pageindex" / "index.json").exists(),
            "graphrag": (root / "graphrag_data" / "graph_index" / "graphrag_ms" / "output").exists(),
            "find": True,
        }
        return {
            "artifact_dir": str(root),
            "artifact_revision": artifact_revision(root),
            "s3_uri": configured_s3_uri(),
            "model": model_id(),
            "documents": [
                {
                    "document_id": record.document_id,
                    "title": record.title,
                    "category": record.category,
                    "pages": len(record.pages),
                    "figures": len(record.figures),
                }
                for record in records
            ],
            "tools": [{"id": method, "ready": ready[method]} for method in RETRIEVAL_METHODS],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Grid artifacts are not ready: {exc}") from exc


@app.post("/api/grid/run")
async def run_grid(request: GridRunRequest) -> StreamingResponse:
    payload = request.model_dump()

    async def event_stream():
        try:
            if _agentcore_runtime_arn():
                for line in _agentcore_event_lines(dict(payload)):
                    if line:
                        yield line
            else:
                payload.pop("runtime_session_id", None)
                async for event in run_grid_agent_events(payload):
                    yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps(
                {"type": "result", "status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Grid Agents local API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("GRID_LOCAL_API_PORT", "8000")))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run("grid_agent_core.local_api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
