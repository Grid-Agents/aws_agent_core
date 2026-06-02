from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


def index_request(
    *, corpus_path: str, chunks_path: str, graph_dir: str, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "op": "index",
        "corpus_path": corpus_path,
        "chunks_path": chunks_path,
        "graph_dir": graph_dir,
        "config": config or {},
    }


def query_request(
    *, query: str, graph_dir: str, top_k: int = 10, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "op": "query",
        "query": query,
        "graph_dir": graph_dir,
        "top_k": top_k,
        "config": config or {},
    }


@dataclass
class WorkerResponse:
    ok: bool
    contexts: list[dict[str, Any]] = field(default_factory=list)
    graph_stats: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def dump_response(response: WorkerResponse) -> str:
    return json.dumps(asdict(response))


def parse_response(text: str) -> WorkerResponse:
    payload = json.loads(text)
    return WorkerResponse(
        ok=bool(payload.get("ok", False)),
        contexts=list(payload.get("contexts", []) or []),
        graph_stats=dict(payload.get("graph_stats", {}) or {}),
        input_tokens=int(payload.get("input_tokens", 0) or 0),
        output_tokens=int(payload.get("output_tokens", 0) or 0),
        error=payload.get("error"),
    )


def parse_worker_stdout(stdout: str) -> WorkerResponse | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "ok" in payload:
            return parse_response(line)
    return None
