from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


META_FILENAME = "INDEX_META.json"


@dataclass
class IndexMeta:
    method: str
    corpus_hash: str
    package_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    built_at_utc: str = ""


def write_index_meta(meta: IndexMeta, graph_dir: Path) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / META_FILENAME).write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")


def read_index_meta(graph_dir: Path) -> IndexMeta | None:
    path = graph_dir / META_FILENAME
    if not path.exists():
        return None
    try:
        return IndexMeta(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def index_is_fresh(graph_dir: Path, *, corpus_hash: str) -> bool:
    meta = read_index_meta(graph_dir)
    return meta is not None and meta.corpus_hash == corpus_hash
