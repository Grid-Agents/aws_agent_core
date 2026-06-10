from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import Iterable
from typing import Any

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import run_grid_agent_events
from .artifacts import artifact_revision, configured_s3_uri, ensure_artifacts, runtime_artifact_dir
from .corpus import load_manifest
from .settings import (
    RETRIEVAL_METHODS,
    colivara_api_key,
    colqwen2_endpoint_name,
    model_id,
    s3_bucket,
    s3_prefix,
)


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
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise RuntimeError("boto3 is required to invoke deployed AgentCore runtime.") from exc
    # The deployed Claude/tool loop can take well over botocore's default 60s read
    # timeout before the first streamed bytes arrive (query embedding via SageMaker,
    # late-interaction scoring, then the agent loop). Use a generous read timeout and
    # disable retries so a slow run is never silently re-invoked.
    read_timeout = int(os.getenv("AGENTCORE_READ_TIMEOUT_SECONDS", "900"))
    return boto3.client(
        "bedrock-agentcore",
        region_name=os.getenv("AWS_REGION"),
        config=Config(
            read_timeout=read_timeout,
            connect_timeout=30,
            retries={"max_attempts": 1},
        ),
    )


def _agentcore_event_lines(payload: dict[str, Any]) -> Iterable[str]:
    arn = _agentcore_runtime_arn()
    if not arn:
        return []
    runtime_session_id = payload.pop("runtime_session_id", None) or str(uuid.uuid4())
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
    decoder = json.JSONDecoder()
    for chunk in raw_lines:
        if not chunk:
            continue
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        for event_text in _agentcore_event_texts(text, content_type=content_type):
            buffered += event_text
            lines, buffered = _pop_json_event_lines(buffered, decoder=decoder, final=False)
            for line in lines:
                yield line
    if buffered.strip():
        lines, buffered = _pop_json_event_lines(buffered, decoder=decoder, final=True)
        for line in lines:
            yield line


def _agentcore_event_texts(text: str, *, content_type: str) -> Iterable[str]:
    if "text/event-stream" not in content_type:
        yield text
        return
    for line in text.splitlines():
        if line.startswith("data: "):
            line = line[6:]
        if line and line != "[DONE]":
            yield line


def _pop_json_event_lines(
    buffered: str,
    *,
    decoder: json.JSONDecoder,
    final: bool,
) -> tuple[list[str], str]:
    lines: list[str] = []
    while buffered.strip():
        stripped = buffered.lstrip()
        try:
            payload, end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            if final:
                lines.append(
                    json.dumps(
                        {"type": "trace", "entry": {"kind": "agentcore", "detail": stripped}},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                return lines, ""
            return lines, buffered
        lines.append(json.dumps(payload, ensure_ascii=False) + "\n")
        buffered = stripped[end:]
    return lines, buffered


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# Serve cited figure crops (and other artifacts) over HTTP for the test console.
# Evidence figure metadata carries a relative `image_path` like
# `figures/grid/<doc>/page-000N-figure-KK.jpg`, so /artifacts/<image_path> resolves it.
_artifact_root = runtime_artifact_dir()
_artifact_root.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(_artifact_root)), name="artifacts")

# Serve the simple local test console (single static page).
_test_ui_dir = Path(__file__).resolve().parents[1] / "test_ui"
if _test_ui_dir.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_test_ui_dir), html=True), name="ui")


@app.get("/api/overview")
async def overview() -> dict[str, Any]:
    try:
        root = ensure_artifacts(runtime_artifact_dir())
        records = load_manifest(root)
        ready = {
            "vector": (root / "indexes" / "vector" / "index.json").exists(),
            "pageindex": (root / "indexes" / "pageindex" / "index.json").exists(),
            "graphrag": (root / "graphrag_data" / "graph_index" / "graphrag_ms" / "output").exists(),
            "colivara": bool(colivara_api_key())
            and (root / "indexes" / "colivara" / "index.json").exists(),
            "colqwen2": bool(colqwen2_endpoint_name())
            and (root / "indexes" / "colqwen2" / "index.json").exists(),
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


# ---- run history persisted to S3 (durable + shared across machines) ----
def _s3_client():
    import boto3

    return boto3.client("s3", region_name=os.getenv("AWS_REGION"))


def _runs_base() -> str:
    prefix = s3_prefix().strip("/")
    return f"{prefix}/runs" if prefix else "runs"


def _safe_run_id(run_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "", str(run_id))[:48]


def _trim_run_result(result: dict[str, Any]) -> dict[str, Any]:
    trimmed = json.loads(json.dumps(result))
    for key in ("evidence", "citations"):
        for item in trimmed.get(key) or []:
            span = item.get("span_text")
            if isinstance(span, str) and len(span) > 700:
                item["span_text"] = span[:700]
    for event in trimmed.get("trajectory") or []:
        detail = event.get("detail")
        if isinstance(detail, str) and len(detail) > 1300:
            event["detail"] = detail[:1300]
    return trimmed


def _run_summary(record: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "ts", "prompt", "methods", "subagents", "filetools", "status", "cited", "retrieved")
    return {key: record.get(key) for key in keys}


def _read_runs_index(client, bucket: str) -> list[dict[str, Any]]:
    try:
        obj = client.get_object(Bucket=bucket, Key=f"{_runs_base()}/index.json")
        data = json.loads(obj["Body"].read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_run_to_s3(payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    bucket = s3_bucket()
    if not bucket:
        return None
    client = _s3_client()
    run_id = str(int(time.time() * 1000))
    record = {
        "id": run_id,
        "ts": int(time.time() * 1000),
        "prompt": payload.get("prompt"),
        "methods": payload.get("methods"),
        "subagents": bool(payload.get("enable_subagents")),
        "filetools": bool(payload.get("allow_sdk_file_tools")),
        "status": result.get("status"),
        "cited": len(result.get("citations") or []),
        "retrieved": len(result.get("evidence") or []),
        "result": _trim_run_result(result),
    }
    base = _runs_base()
    client.put_object(
        Bucket=bucket,
        Key=f"{base}/{run_id}.json",
        Body=json.dumps(record, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    index = _read_runs_index(client, bucket)
    index.insert(0, _run_summary(record))
    index = index[:200]
    client.put_object(
        Bucket=bucket,
        Key=f"{base}/index.json",
        Body=json.dumps(index, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return run_id


@app.get("/api/runs")
async def list_runs() -> dict[str, Any]:
    bucket = s3_bucket()
    if not bucket:
        return {"runs": [], "s3": False}
    try:
        return {
            "runs": _read_runs_index(_s3_client(), bucket),
            "s3": True,
            "uri": f"{configured_s3_uri()}/runs",
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot list runs from S3: {exc}") from exc


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    bucket = s3_bucket()
    if not bucket:
        raise HTTPException(status_code=404, detail="No S3 bucket configured.")
    try:
        obj = _s3_client().get_object(Bucket=bucket, Key=f"{_runs_base()}/{_safe_run_id(run_id)}.json")
        return json.loads(obj["Body"].read())
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@app.delete("/api/runs")
async def clear_runs() -> dict[str, Any]:
    bucket = s3_bucket()
    if not bucket:
        return {"deleted": 0}
    client = _s3_client()
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{_runs_base()}/"):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=item["Key"])
            deleted += 1
    return {"deleted": deleted}


@app.post("/api/grid/run")
async def run_grid(request: GridRunRequest) -> StreamingResponse:
    payload = request.model_dump()

    async def event_stream():
        try:
            runtime_arn = _agentcore_runtime_arn()
            if runtime_arn:
                qualifier = os.getenv("AGENTCORE_RUNTIME_QUALIFIER", "").strip()
                yield json.dumps(
                    {
                        "type": "trace",
                        "entry": {
                            "id": 0,
                            "kind": "agentcore",
                            "title": "Invoking deployed AgentCore runtime",
                            "detail": (
                                "Forwarding this request to AWS Bedrock AgentCore. "
                                "The deployed Claude/tool loop can take 60-120 seconds "
                                "before model events arrive."
                            ),
                            "metadata": {
                                "runtime_arn": runtime_arn,
                                "qualifier": qualifier or None,
                            },
                        },
                    },
                    ensure_ascii=False,
                ) + "\n"
                await asyncio.sleep(0)
                for line in _agentcore_event_lines(dict(payload)):
                    if line:
                        try:
                            event = json.loads(line)
                            if event.get("type") == "result":
                                save_run_to_s3(payload, event)
                        except Exception as exc:  # never break the stream on a save failure
                            print(f"[runs] failed to save deployed run to S3: {exc}")
                        yield line
            else:
                payload.pop("runtime_session_id", None)
                async for event in run_grid_agent_events(payload):
                    if event.get("type") == "result":
                        try:
                            save_run_to_s3(payload, event)
                        except Exception as exc:  # never break the stream on a save failure
                            print(f"[runs] failed to save run to S3: {exc}")
                    yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            yield json.dumps(
                {
                    "type": "trace",
                    "entry": {
                        "id": 0,
                        "kind": "error",
                        "title": "Proxy or AgentCore invocation failed",
                        "detail": message,
                        "metadata": {},
                    },
                },
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps(
                {"type": "result", "status": "error", "error": message},
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
