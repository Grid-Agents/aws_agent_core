from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .corpus import document_text, load_manifest
from .progress import ProgressBar
from .rag_compat.grid_llm import make_pageindex_llm
from .rag_compat.official_pageindex import OfficialPageIndexRAG
from .rag_compat.types import Document
from .rag_compat.vector_rag import VectorRAG
from .settings import DEFAULT_ARTIFACT_DIR

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'-]*")
GRAPHRAG_METHOD = "graphrag_ms"
GRAPHRAG_REQUIRED_MODULES = (
    "graphrag",
    "lancedb",
    "litellm",
)


def _graphrag_python() -> str:
    """Interpreter that runs the GraphRAG worker subprocess.

    GraphRAG (and its `spacy` dependency) only support CPython <= 3.13, while the
    main app/runtime runs on 3.14, so the worker lives in its own venv. Set
    GRID_GRAPHRAG_PYTHON to that venv's python; defaults to the current interpreter.
    """
    return os.getenv("GRID_GRAPHRAG_PYTHON", sys.executable)
PAGEINDEX_LOGIC = "vector_pageindex_rag_eval.OfficialPageIndexRAG"
PAGEINDEX_REPO_URL = "https://github.com/VectifyAI/PageIndex.git"


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    start_char: int
    end_char: int
    text: str
    score: float
    source: str
    section: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def tokenize(text: str) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN.finditer(text)]


def _artifact_revision(artifact_dir: Path) -> str:
    revision_path = artifact_dir / "artifact_revision.txt"
    if revision_path.exists():
        return revision_path.read_text(encoding="utf-8").strip()
    records = load_manifest(artifact_dir)
    return hashlib.sha256(
        "\n".join(
            f"{record.document_id}:{record.text_sha256}:"
            + ",".join(f"{figure.figure_id}:{figure.image_sha256}" for figure in record.figures)
            for record in records
        ).encode("utf-8")
    ).hexdigest()


def _write_json_file(path: Path, payload: Any, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent), encoding="utf-8")
    temp_path.replace(path)


def _read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _index_is_current(index_dir: Path, *, expected: dict[str, Any]) -> bool:
    index_path = index_dir / "index.json"
    meta = _read_json_file(index_dir / "index_meta.json")
    if not index_path.exists() or not isinstance(meta, dict):
        return False
    return all(meta.get(key) == value for key, value in expected.items())


def _write_index_meta(index_dir: Path, payload: dict[str, Any]) -> None:
    _write_json_file(
        index_dir / "index_meta.json",
        {
            **payload,
            "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        indent=2,
    )


def _documents(artifact_dir: Path, records: list[Any] | None = None) -> list[Document]:
    return [
        Document(record.document_id, document_text(artifact_dir, record))
        for record in (records or load_manifest(artifact_dir))
    ]


def _document_payload(records: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": record.document_id,
            "title": record.title,
            "category": record.category,
            "filename": record.filename,
            "text_sha256": record.text_sha256,
        }
        for record in records
    ]


def _vector_config(
    *,
    provider: str,
    chunk_strategy: str,
    search_strategy: str,
    cache_dir: Path,
    force_reindex: bool,
) -> dict[str, Any]:
    provider = _normalize_vector_provider(provider)
    cfg: dict[str, Any] = {
        "cache_dir": str(cache_dir),
        "force_reindex": force_reindex,
        "chunk_strategy": chunk_strategy,
        "search_strategy": search_strategy,
        "chunk_size": int(os.getenv("GRID_VECTOR_CHUNK_SIZE", "1200")),
        "chunk_overlap": int(os.getenv("GRID_VECTOR_CHUNK_OVERLAP", "120")),
        "semantic_chunking": {
            "break_percentile": float(os.getenv("GRID_VECTOR_SEMANTIC_BREAK_PERCENTILE", "82")),
            "window_size": int(os.getenv("GRID_VECTOR_SEMANTIC_WINDOW_SIZE", "3")),
            "min_chunk_size": _optional_int(os.getenv("GRID_VECTOR_SEMANTIC_MIN_CHUNK_SIZE")),
        },
        "hybrid": {
            "vector_weight": float(os.getenv("GRID_VECTOR_HYBRID_VECTOR_WEIGHT", "0.65")),
            "bm25_weight": float(os.getenv("GRID_VECTOR_HYBRID_BM25_WEIGHT", "0.35")),
            "bm25_k1": float(os.getenv("GRID_VECTOR_HYBRID_BM25_K1", "1.5")),
            "bm25_b": float(os.getenv("GRID_VECTOR_HYBRID_BM25_B", "0.75")),
        },
        "top_k": int(os.getenv("GRID_VECTOR_TOP_K", "20")),
        "batch_size": int(os.getenv("GRID_VECTOR_BATCH_SIZE", "128")),
    }
    if provider == "voyage":
        cfg.update(
            {
                "embedding_provider": "voyage",
                "embedding_model": os.getenv("GRID_VECTOR_EMBEDDING_MODEL", "voyage-law-2"),
                "query_instruction": "",
                "embedding_output_dimension": _optional_int(os.getenv("GRID_VECTOR_EMBEDDING_OUTPUT_DIMENSION")),
                "embedding_truncation": _env_bool("GRID_VECTOR_EMBEDDING_TRUNCATION", True),
                "reranker": {
                    "enabled": _env_bool("GRID_VECTOR_RERANKER_ENABLED", True),
                    "provider": "voyage",
                    "model": os.getenv("GRID_VECTOR_RERANKER_MODEL", "rerank-2"),
                    "top_k": int(os.getenv("GRID_VECTOR_RERANK_TOP_K", "8")),
                },
            }
        )
    else:
        cfg.update(
            {
                "embedding_provider": "sentence_transformers",
                "embedding_model": os.getenv("GRID_VECTOR_EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"),
                "query_instruction": os.getenv(
                    "GRID_VECTOR_QUERY_INSTRUCTION",
                    "Represent this sentence for searching relevant passages: ",
                ),
                "batch_size": int(os.getenv("GRID_VECTOR_BATCH_SIZE", "8")),
                "reranker": {
                    "enabled": _env_bool("GRID_VECTOR_RERANKER_ENABLED", True),
                    "provider": "sentence_transformers",
                    "model": os.getenv("GRID_VECTOR_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
                    "top_k": int(os.getenv("GRID_VECTOR_RERANK_TOP_K", "8")),
                },
            }
        )
    return cfg


def build_vector_index(
    artifact_dir: Path,
    *,
    provider: str = "voyage",
    chunk_strategy: str = "semantic",
    search_strategy: str = "hybrid",
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
) -> Path:
    del show_progress
    records = load_manifest(artifact_dir)
    revision = _artifact_revision(artifact_dir)
    index_dir = artifact_dir / "indexes" / "vector"
    cache_dir = index_dir / "cache"
    path = index_dir / "index.json"
    cfg = _vector_config(
        provider=provider,
        chunk_strategy=chunk_strategy,
        search_strategy=search_strategy,
        cache_dir=cache_dir,
        force_reindex=rebuild or not resume,
    )
    expected_meta = {
        "method": "vector",
        "artifact_revision": revision,
        "logic": "vector_pageindex_rag_eval.VectorRAG",
        "embedding_provider": cfg["embedding_provider"],
        "embedding_model": cfg["embedding_model"],
        "chunk_strategy": chunk_strategy,
        "search_strategy": search_strategy,
    }
    if resume and not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("vector: index fresh, skipping (use --rebuild-indexes to force)")
        return path

    vector = VectorRAG(cfg, cache_dir=cache_dir)
    vector.build(_documents(artifact_dir, records))
    chunk_count = len(vector.chunks)
    _write_json_file(index_dir / "config.json", {**cfg, "force_reindex": False}, indent=2)
    _write_json_file(
        path,
        {
            "method": "vector",
            "logic": "vector_pageindex_rag_eval.VectorRAG",
            "artifact_revision": revision,
            "document_count": len(records),
            "chunk_count": chunk_count,
            "documents": _document_payload(records),
        },
        indent=2,
    )
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(records),
            "chunk_count": chunk_count,
        },
    )
    return path


def load_vector_hits(artifact_dir: Path, query: str, *, top_k: int = 8) -> list[SearchHit]:
    index_dir = artifact_dir / "indexes" / "vector"
    path = index_dir / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing vector index: {path}")
    cfg = _read_json_file(index_dir / "config.json")
    if not isinstance(cfg, dict):
        raise FileNotFoundError(f"Missing vector index config: {index_dir / 'config.json'}")
    cfg = _query_vector_config(cfg, top_k=top_k)
    vector = VectorRAG(cfg, cache_dir=index_dir / "cache")
    vector.build(_documents(artifact_dir))
    output = vector.query(query)
    return [
        SearchHit(
            document_id=span.document_id,
            start_char=span.start_char,
            end_char=span.end_char,
            text=span.text,
            score=span.score,
            source="vector",
            section=str(span.metadata.get("chunk_title", "")),
        )
        for span in output.spans[:top_k]
    ]


def _pageindex_config(*, cache_dir: Path, force_reindex: bool) -> dict[str, Any]:
    return {
        "cache_dir": str(cache_dir),
        "force_reindex": force_reindex,
        "repo_url": os.getenv("GRID_PAGEINDEX_REPO_URL", PAGEINDEX_REPO_URL),
        "repo_ref": os.getenv("GRID_PAGEINDEX_REPO_REF", "main"),
        "repo_path": os.getenv("GRID_PAGEINDEX_REPO_PATH", ""),
        "auto_clone_repo": _env_bool("GRID_PAGEINDEX_AUTO_CLONE_REPO", True),
        "build_with_llm": _env_bool("GRID_PAGEINDEX_BUILD_WITH_LLM", True),
        "virtual_page_target_tokens": int(os.getenv("GRID_PAGEINDEX_VIRTUAL_PAGE_TARGET_TOKENS", "900")),
        "virtual_page_max_tokens": int(os.getenv("GRID_PAGEINDEX_VIRTUAL_PAGE_MAX_TOKENS", "1200")),
        "if_thinning": _env_bool("GRID_PAGEINDEX_IF_THINNING", False),
        "thinning_threshold": int(os.getenv("GRID_PAGEINDEX_THINNING_THRESHOLD", "5000")),
        "if_add_node_summary": os.getenv("GRID_PAGEINDEX_IF_ADD_NODE_SUMMARY", "yes"),
        "if_add_doc_description": os.getenv("GRID_PAGEINDEX_IF_ADD_DOC_DESCRIPTION", "yes"),
        "if_add_node_text": os.getenv("GRID_PAGEINDEX_IF_ADD_NODE_TEXT", "no"),
        "summary_token_threshold": int(os.getenv("GRID_PAGEINDEX_SUMMARY_TOKEN_THRESHOLD", "200")),
        "selected_documents": int(os.getenv("GRID_PAGEINDEX_SELECTED_DOCUMENTS", "5")),
        "max_document_catalog_chars": int(os.getenv("GRID_PAGEINDEX_MAX_DOCUMENT_CATALOG_CHARS", "120000")),
        "max_document_catalog_candidates": int(os.getenv("GRID_PAGEINDEX_MAX_DOCUMENT_CATALOG_CANDIDATES", "80")),
        "max_tree_chars": int(os.getenv("GRID_PAGEINDEX_MAX_TREE_CHARS", "24000")),
        "selected_nodes": int(os.getenv("GRID_PAGEINDEX_SELECTED_NODES", "10")),
        "max_retrieved_chars_per_node": int(os.getenv("GRID_PAGEINDEX_MAX_RETRIEVED_CHARS_PER_NODE", "5000")),
        "record_reasoning_trajectory": _env_bool("GRID_PAGEINDEX_RECORD_REASONING_TRAJECTORY", True),
        "reasoning_max_catalog_chars": int(os.getenv("GRID_PAGEINDEX_REASONING_MAX_CATALOG_CHARS", "12000")),
        "reasoning_max_node_summary_chars": int(os.getenv("GRID_PAGEINDEX_REASONING_MAX_NODE_SUMMARY_CHARS", "320")),
        "reasoning_max_trace_nodes": int(os.getenv("GRID_PAGEINDEX_REASONING_MAX_TRACE_NODES", "250")),
    }


def build_pageindex(
    artifact_dir: Path,
    *,
    anthropic_batch: bool = False,
    model: str | None = None,
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
) -> Path:
    del show_progress
    if anthropic_batch:
        raise RuntimeError(
            "The vector_pageindex_rag_eval official PageIndex implementation does not use "
            "Anthropic Message Batches. Build without --anthropic-batch."
        )
    records = load_manifest(artifact_dir)
    revision = _artifact_revision(artifact_dir)
    index_dir = artifact_dir / "indexes" / "pageindex"
    cache_dir = index_dir / "cache"
    path = index_dir / "index.json"
    cfg = _pageindex_config(cache_dir=cache_dir, force_reindex=rebuild or not resume)
    expected_meta = {
        "method": "pageindex",
        "artifact_revision": revision,
        "logic": PAGEINDEX_LOGIC,
        "build_with_llm": bool(cfg.get("build_with_llm", True)),
        "repo_url": cfg.get("repo_url"),
        "repo_ref": cfg.get("repo_ref"),
        "repo_path": cfg.get("repo_path"),
    }
    if resume and not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("pageindex: index fresh, skipping (use --rebuild-indexes to force)")
        return path

    llm = make_pageindex_llm({"model": model} if model else {}) if cfg.get("build_with_llm", True) else None
    pageindex = OfficialPageIndexRAG(cfg, llm, cache_dir=cache_dir)
    pageindex.build(_documents(artifact_dir, records))
    _write_json_file(index_dir / "config.json", {**cfg, "force_reindex": False}, indent=2)
    _write_json_file(
        path,
        {
            "method": "pageindex",
            "logic": PAGEINDEX_LOGIC,
            "artifact_revision": revision,
            "document_count": len(records),
            "setup_usage": pageindex.setup_usage.to_dict(),
            "documents": _document_payload(records),
        },
        indent=2,
    )
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(records),
            "setup_usage": pageindex.setup_usage.to_dict(),
        },
    )
    return path


def load_pageindex_hits(artifact_dir: Path, query: str, *, top_k: int = 8) -> list[SearchHit]:
    index_dir = artifact_dir / "indexes" / "pageindex"
    path = index_dir / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing PageIndex index: {path}")
    index_payload = _read_json_file(path)
    if not isinstance(index_payload, dict) or index_payload.get("logic") != PAGEINDEX_LOGIC:
        raise RuntimeError(
            "PageIndex index was not built with the official PageIndex adapter. "
            "Rebuild it with `uv run grid-build-indexes --methods pageindex --rebuild-indexes`."
        )
    cfg = _read_json_file(index_dir / "config.json")
    if not isinstance(cfg, dict):
        raise FileNotFoundError(f"Missing PageIndex index config: {index_dir / 'config.json'}")
    cfg["force_reindex"] = False
    cfg["selected_nodes"] = max(int(cfg.get("selected_nodes", 1)), top_k)
    llm = make_pageindex_llm({})
    pageindex = OfficialPageIndexRAG(cfg, llm, cache_dir=index_dir / "cache")
    pageindex.build(_documents(artifact_dir))
    output = pageindex.query(query)
    return [
        SearchHit(
            document_id=span.document_id,
            start_char=span.start_char,
            end_char=span.end_char,
            text=span.text,
            score=span.score,
            source="pageindex",
            section=str(span.metadata.get("node_title", "")),
        )
        for span in output.spans[:top_k]
    ]


def build_graphrag_prerequisites(artifact_dir: Path, *, show_progress: bool = False) -> Path:
    from .graphrag.canonical_chunks import build_canonical_chunks, write_canonical_chunks

    records = load_manifest(artifact_dir)
    data_dir = artifact_dir / "graphrag_data"
    corpus_dir = data_dir / "corpus" / "grid"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    corpus: dict[str, str] = {}
    progress = ProgressBar("GraphRAG prerequisites", len(records), enabled=show_progress)
    try:
        for record in records:
            source = artifact_dir / record.text_path
            target = corpus_dir / Path(record.text_path).name
            text = source.read_text(encoding="utf-8")
            target.write_text(text, encoding="utf-8")
            corpus[record.document_id] = text
            progress.advance(detail=record.filename)
    except Exception:
        progress.fail()
        raise
    progress.close()
    index_root = data_dir / "graph_index"
    index_root.mkdir(parents=True, exist_ok=True)
    _write_json_file(index_root / "corpus.json", corpus)
    write_canonical_chunks(
        build_canonical_chunks(corpus),
        index_root / "canonical_chunks.json",
    )
    return data_dir


def corpus_hash(corpus: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for document_id in sorted(corpus):
        digest.update(document_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(corpus[document_id].encode("utf-8")).digest())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _missing_graphrag_dependencies() -> list[str]:
    # graphrag lives in the worker interpreter (see _graphrag_python), which may differ
    # from the orchestrator's. Probe that interpreter rather than the current one.
    py = _graphrag_python()
    if py == sys.executable:
        return [m for m in GRAPHRAG_REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    code = (
        "import importlib.util;"
        f"mods={list(GRAPHRAG_REQUIRED_MODULES)!r};"
        "print(','.join(m for m in mods if importlib.util.find_spec(m) is None))"
    )
    try:
        out = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=30)
    except Exception:
        return list(GRAPHRAG_REQUIRED_MODULES)
    return [m for m in out.stdout.strip().split(",") if m]


def build_graphrag_index(artifact_dir: Path, *, rebuild: bool = False, show_progress: bool = False) -> None:
    from .graphrag.index_meta import IndexMeta, index_is_fresh, write_index_meta
    from .graphrag.worker_protocol import index_request, parse_worker_stdout

    data_dir = build_graphrag_prerequisites(artifact_dir, show_progress=show_progress)
    missing = _missing_graphrag_dependencies()
    if missing:
        raise RuntimeError(
            "GraphRAG Python dependencies are missing in this project environment: "
            f"{', '.join(missing)}. GraphRAG is optional and currently supported "
            "through a Python 3.12 worker environment. Run "
            "`uv sync --python 3.12 --extra graphrag` in app/GridAgentCore, or set "
            "GRID_GRAPHRAG_PYTHON to a Python 3.12 interpreter with GraphRAG installed, "
            "then retry `uv run grid-build-indexes --methods graphrag`."
        )
    index_root = data_dir / "graph_index"
    corpus_path = index_root / "corpus.json"
    chunks_path = index_root / "canonical_chunks.json"
    graph_dir = index_root / GRAPHRAG_METHOD
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    hash_value = corpus_hash(corpus)
    if index_is_fresh(graph_dir, corpus_hash=hash_value) and not rebuild:
        print(f"{GRAPHRAG_METHOD}: index fresh, skipping (use --rebuild-graphrag to force)")
        return
    request = index_request(
        corpus_path=str(corpus_path),
        chunks_path=str(chunks_path),
        graph_dir=str(graph_dir),
        config={"corpus_hash": hash_value},
    )
    command = [
        _graphrag_python(),
        "-m",
        "grid_agent_core.graphrag.graphrag_ms_worker",
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = subprocess.run(
        command,
        input=json.dumps(request),
        capture_output=True,
        env=env,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "Local GraphRAG worker exited "
            f"{process.returncode}: {process.stderr[-800:] or process.stdout[-800:]}"
        )
    response = parse_worker_stdout(process.stdout)
    if response is None:
        raise RuntimeError("Local GraphRAG worker returned no parseable JSON response.")
    if not response.ok:
        raise RuntimeError(f"Local GraphRAG worker error: {response.error}")
    write_index_meta(
        IndexMeta(
            method=GRAPHRAG_METHOD,
            corpus_hash=hash_value,
            package_version=str(response.graph_stats.get("package_version", "unknown")),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=0.0,
            built_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
        graph_dir,
    )


def load_graphrag_hits(artifact_dir: Path, query: str, *, top_k: int = 8) -> list[SearchHit]:
    from .graphrag.index_meta import index_is_fresh
    from .graphrag.span_resolver import resolve_spans
    from .graphrag.worker_protocol import parse_worker_stdout, query_request

    index_root = artifact_dir / "graphrag_data" / "graph_index"
    corpus_path = index_root / "corpus.json"
    graph_dir = index_root / GRAPHRAG_METHOD
    if not corpus_path.exists():
        raise FileNotFoundError(f"Missing GraphRAG corpus: {corpus_path}")
    corpus: dict[str, str] = json.loads(corpus_path.read_text(encoding="utf-8"))
    hash_value = corpus_hash(corpus)
    if not index_is_fresh(graph_dir, corpus_hash=hash_value):
        raise FileNotFoundError(
            f"GraphRAG index missing or stale for {GRAPHRAG_METHOD}: {graph_dir}"
        )
    request = query_request(
        query=query,
        graph_dir=str(graph_dir),
        top_k=top_k,
        config={"corpus_hash": hash_value},
    )
    process = subprocess.run(
        [_graphrag_python(), "-m", "grid_agent_core.graphrag.graphrag_ms_worker"],
        input=json.dumps(request),
        capture_output=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        text=True,
        timeout=int(os.getenv("GRID_GRAPHRAG_QUERY_TIMEOUT_SECONDS", "180")),
    )
    if process.returncode != 0:
        raise RuntimeError(
            "Local GraphRAG worker exited "
            f"{process.returncode}: {process.stderr[-800:] or process.stdout[-800:]}"
        )
    response = parse_worker_stdout(process.stdout)
    if response is None:
        raise RuntimeError("Local GraphRAG worker returned no parseable JSON response.")
    if not response.ok:
        raise RuntimeError(f"Local GraphRAG worker error: {response.error}")
    spans, dropped = resolve_spans(response.contexts, corpus)
    scores = _graphrag_context_scores(response.contexts)
    hits = [
        SearchHit(
            document_id=span.document_id,
            start_char=span.start_char,
            end_char=span.end_char,
            text=span.snippet,
            score=scores.get((span.document_id, span.snippet), 0.0),
            source="graphrag",
            section=f"GraphRAG text unit; dropped={dropped}",
        )
        for span in spans
    ]
    return hits[:top_k]


def build_all(
    artifact_dir: Path,
    *,
    methods: list[str],
    anthropic_batch: bool = False,
    resume: bool = True,
    rebuild_indexes: bool = False,
    rebuild_graphrag: bool = False,
    vector_provider: str = "voyage",
    vector_chunk_strategy: str = "semantic",
    vector_search_strategy: str = "hybrid",
    show_progress: bool = False,
) -> None:
    start = time.time()
    try:
        records = load_manifest(artifact_dir)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Missing parsed Grid corpus in {artifact_dir}. "
            "Run `uv run grid-parse-documents --source-dir <Grid Docs> "
            "--artifact-dir <artifact dir>` before building indexes."
        ) from exc
    selected = set(methods)
    if "vector" in selected:
        print(
            "Building vector_pageindex_rag_eval VectorRAG index "
            f"for {len(records)} documents..."
        )
        build_vector_index(
            artifact_dir,
            provider=vector_provider,
            chunk_strategy=vector_chunk_strategy,
            search_strategy=vector_search_strategy,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    if "pageindex" in selected:
        print("Building vector_pageindex_rag_eval OfficialPageIndexRAG index...")
        build_pageindex(
            artifact_dir,
            anthropic_batch=anthropic_batch,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    if "graphrag" in selected:
        print("Building rlm-eval GraphRAG index with local graphrag_ms worker...")
        build_graphrag_index(
            artifact_dir,
            rebuild=rebuild_graphrag,
            show_progress=show_progress,
        )
    if "colivara" in selected:
        from .colivara import build_colivara_index

        print("Syncing Grid PDFs to ColiVara visual retrieval...")
        build_colivara_index(
            artifact_dir,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    if "colqwen2" in selected:
        from .colqwen2 import build_colqwen2_index

        print("Building AWS ColQwen2 visual multi-vector index...")
        build_colqwen2_index(
            artifact_dir,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    print(f"Grid index build finished in {time.time() - start:.1f}s")


def _query_vector_config(cfg: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    cfg = dict(cfg)
    cfg["force_reindex"] = False
    cfg["top_k"] = max(int(cfg.get("top_k", 1)), top_k)
    reranker = dict(cfg.get("reranker") or {})
    if reranker.get("enabled", True):
        reranker["top_k"] = max(int(reranker.get("top_k", 1)), top_k)
        cfg["reranker"] = reranker
    return cfg


def _normalize_vector_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"voyage", "voyageai"}:
        return "voyage"
    if normalized in {"sentence_transformers", "sentence_transformer", "st", "bge"}:
        return "sentence_transformers"
    raise ValueError("vector provider must be 'voyage' or 'sentence_transformers'.")


def _optional_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _graphrag_context_scores(contexts: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {
        (str(context.get("document_id", "")), str(context.get("text", "") or "")): float(
            context.get("score", 0.0) or 0.0
        )
        for context in contexts
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Grid document indexes.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--methods", default="vector,pageindex,graphrag")
    parser.add_argument("--source-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--anthropic-batch", action="store_true")
    parser.add_argument("--rebuild-indexes", action="store_true")
    parser.add_argument("--rebuild-graphrag", action="store_true")
    parser.add_argument("--no-resume", action="store_true", help="Ignore VectorRAG/PageIndex cache files.")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars.")
    parser.add_argument(
        "--vector-provider",
        choices=["voyage", "sentence_transformers"],
        default="voyage",
    )
    parser.add_argument(
        "--chunk-strategy",
        choices=["semantic", "hierarchical", "recursive", "fixed"],
        default="semantic",
        help="VectorRAG chunking strategy from vector_pageindex_rag_eval.",
    )
    parser.add_argument(
        "--search-strategy",
        choices=["hybrid", "vector"],
        default="hybrid",
        help="VectorRAG search strategy from vector_pageindex_rag_eval.",
    )
    args = parser.parse_args()
    if args.source_dir is not None:
        print("Ignoring --source-dir during indexing; run grid-parse-documents first.")
    rebuild_indexes = args.rebuild_indexes
    if args.force:
        rebuild_indexes = True
        print("Treating --force as --rebuild-indexes during indexing.")
    methods = []
    valid_methods = {"vector", "pageindex", "graphrag", "colivara", "colqwen2"}
    for item in args.methods.split(","):
        method = item.strip()
        if not method:
            continue
        if method == "find":
            print("Skipping find: exact-find uses the parsed corpus directly and has no index.")
            continue
        if method not in valid_methods:
            raise ValueError(f"Unsupported index method: {method}")
        methods.append(method)
    if not methods:
        print("No index methods selected.")
        return
    build_all(
        args.artifact_dir,
        methods=methods,
        anthropic_batch=args.anthropic_batch,
        resume=not args.no_resume,
        rebuild_indexes=rebuild_indexes,
        rebuild_graphrag=args.rebuild_graphrag,
        vector_provider=args.vector_provider,
        vector_chunk_strategy=args.chunk_strategy,
        vector_search_strategy=args.search_strategy,
        show_progress=not args.no_progress,
    )


if __name__ == "__main__":
    main()
