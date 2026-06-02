from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable


def read_request() -> dict[str, Any]:
    return json.loads(sys.stdin.read())


def load_corpus(corpus_path: str) -> dict[str, str]:
    with open(corpus_path, encoding="utf-8") as handle:
        return json.load(handle)


def load_chunks(chunks_path: str) -> list[dict[str, Any]]:
    with open(chunks_path, encoding="utf-8") as handle:
        return json.load(handle)


def emit(
    ok: bool,
    *,
    contexts: list[dict[str, Any]] | None = None,
    graph_stats: dict[str, Any] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str | None = None,
) -> None:
    print(
        json.dumps(
            {
                "ok": ok,
                "contexts": contexts or [],
                "graph_stats": graph_stats or {},
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error": error,
            }
        ),
        flush=True,
    )


def run_worker(
    index_fn: Callable[[dict[str, Any]], dict[str, Any]],
    query_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    try:
        request = read_request()
        if request.get("op") == "index":
            emit(True, **index_fn(request))
        elif request.get("op") == "query":
            emit(True, **query_fn(request))
        else:
            emit(False, error=f"unknown op: {request.get('op')}")
    except Exception as exc:  # noqa: BLE001 - subprocess worker must not fail silently
        emit(False, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
