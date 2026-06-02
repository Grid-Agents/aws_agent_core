from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from .corpus import document_text, load_manifest
from .graphrag.canonical_chunks import build_canonical_chunks, write_canonical_chunks
from .graphrag.index_meta import IndexMeta, index_is_fresh, write_index_meta
from .graphrag.worker_protocol import index_request, parse_worker_stdout
from .progress import ProgressBar
from .settings import DEFAULT_ARTIFACT_DIR, batch_model

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}")
CHUNK_SIZE = 1800
CHUNK_OVERLAP = 220
GRAPHRAG_METHOD = "graphrag_ms"
GRAPHRAG_REQUIRED_MODULES = (
    "graphrag",
    "lancedb",
    "litellm",
)


def _json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def _part_path(parts_dir: Path, document_id: str) -> Path:
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:16]
    return parts_dir / f"{digest}.json"


def _write_json_file(path: Path, payload: Any, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
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
    meta = {
        **payload,
        "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json_file(index_dir / "index_meta.json", meta, indent=2)


def tokenize(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN.findall(text)]


def make_chunks(text: str, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunk_start = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            chunks.append((chunk_start, chunk_start + len(chunk), chunk))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _term_vector(text: str) -> dict[str, float]:
    counts = Counter(tokenize(text))
    length = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {term: value / length for term, value in counts.items()}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(term, 0.0) for term, weight in left.items())


def _voyage_embeddings(texts: list[str], *, input_type: str) -> list[list[float]]:
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY is required for --vector-provider voyage. "
            "Use --vector-provider local for the deterministic local fallback."
        )
    import voyageai

    client = voyageai.Client(api_key=api_key)
    result = client.embed(texts, model="voyage-law-2", input_type=input_type)
    return [list(vector) for vector in result.embeddings]


def build_vector_index(
    artifact_dir: Path,
    *,
    provider: str = "local",
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
) -> Path:
    records = load_manifest(artifact_dir)
    revision = _artifact_revision(artifact_dir)
    index_dir = artifact_dir / "indexes" / "vector"
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / "index.json"
    expected_meta = {
        "method": "vector",
        "artifact_revision": revision,
        "provider": provider,
    }
    if not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("vector: index fresh, skipping (use --rebuild-indexes to force)")
        return path

    parts_dir = index_dir / "parts" / provider
    chunks: list[dict[str, Any]] = []
    progress = ProgressBar("Vector index", len(records), enabled=show_progress)
    try:
        for record in records:
            part = _load_vector_part(parts_dir, record, provider=provider) if resume else None
            detail = f"resume {record.filename}"
            if part is None:
                part = _build_vector_part(artifact_dir, record, provider=provider)
                _write_json_file(_part_path(parts_dir, record.document_id), part)
                detail = f"built {record.filename}"
            chunks.extend(list(part.get("chunks") or []))
            progress.advance(detail=detail)
    except Exception:
        progress.fail()
        raise
    progress.close()

    payload = {"provider": provider, "chunk_count": len(chunks), "chunks": chunks}
    _write_json_file(path, payload)
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(records),
            "chunk_count": len(chunks),
        },
    )
    return path


def _build_vector_part(artifact_dir: Path, record: Any, *, provider: str) -> dict[str, Any]:
    text = document_text(artifact_dir, record)
    chunks: list[dict[str, Any]] = []
    for index, (start, end, chunk) in enumerate(make_chunks(text), start=1):
        chunks.append(
            {
                "chunk_id": f"{record.document_id}#c{index:04d}",
                "document_id": record.document_id,
                "start_char": start,
                "end_char": end,
                "text": chunk,
            }
        )
    if provider == "voyage" and chunks:
        embeddings = _voyage_embeddings(
            [chunk["text"] for chunk in chunks],
            input_type="document",
        )
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
    elif provider == "local":
        for chunk in chunks:
            chunk["vector"] = _term_vector(chunk["text"])
    elif provider != "voyage":
        raise ValueError("vector provider must be 'voyage' or 'local'.")
    return {
        "method": "vector",
        "provider": provider,
        "document_id": record.document_id,
        "text_sha256": record.text_sha256,
        "chunks": chunks,
    }


def _load_vector_part(parts_dir: Path, record: Any, *, provider: str) -> dict[str, Any] | None:
    payload = _read_json_file(_part_path(parts_dir, record.document_id))
    if not isinstance(payload, dict):
        return None
    expected = {
        "method": "vector",
        "provider": provider,
        "document_id": record.document_id,
        "text_sha256": record.text_sha256,
    }
    if not all(payload.get(key) == value for key, value in expected.items()):
        return None
    chunks = payload.get("chunks")
    return payload if isinstance(chunks, list) else None


def _page_summary(text: str, max_chars: int = 900) -> str:
    compact = " ".join(text.split())
    return compact[:max_chars]


def _batch_requests(records: list[Any], artifact_dir: Path, model: str) -> list[dict[str, Any]]:
    requests = []
    for record in records:
        text = document_text(artifact_dir, record)
        for page in record.pages:
            page_text = text[page.start_char : page.end_char]
            requests.append(
                {
                    "custom_id": f"{record.document_id}|p{page.page}",
                    "params": {
                        "model": model,
                        "max_tokens": 180,
                        "temperature": 0,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Summarize this Grid regulation page for retrieval. "
                                    "Return one concise paragraph with key obligations, "
                                    "definitions, codes, dates, and entities.\n\n"
                                    f"Document: {record.title}\nPage: {page.page}\n\n{page_text[:12000]}"
                                ),
                            }
                        ],
                    },
                }
            )
    return requests


def submit_pageindex_batch(artifact_dir: Path, *, model: str, resume: bool = True) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for --anthropic-batch.")
    records = load_manifest(artifact_dir)
    requests = _batch_requests(records, artifact_dir, model)
    batch_dir = artifact_dir / "indexes" / "pageindex"
    batch_dir.mkdir(parents=True, exist_ok=True)
    request_hash = _json_hash(requests)
    batch_id_path = batch_dir / "batch_id.txt"
    batch_meta_path = batch_dir / "batch_meta.json"
    batch_meta = _read_json_file(batch_meta_path)
    if (
        resume
        and batch_id_path.exists()
        and isinstance(batch_meta, dict)
        and batch_meta.get("request_hash") == request_hash
        and batch_meta.get("model") == model
    ):
        batch_id = batch_id_path.read_text(encoding="utf-8").strip()
        print(f"pageindex: reusing submitted Anthropic Message Batch {batch_id}")
        return batch_id
    _write_json_file(batch_dir / "batch_requests.json", requests, indent=2)
    client = Anthropic(api_key=api_key)
    batch = client.messages.batches.create(requests=requests)
    batch_id = str(batch.id)
    (batch_dir / "batch_id.txt").write_text(batch_id + "\n", encoding="utf-8")
    (batch_dir / "batch_submitted.json").write_text(
        batch.model_dump_json(indent=2),
        encoding="utf-8",
    )
    _write_json_file(
        batch_meta_path,
        {
            "request_hash": request_hash,
            "model": model,
            "request_count": len(requests),
            "batch_id": batch_id,
        },
        indent=2,
    )
    return batch_id


def build_pageindex(
    artifact_dir: Path,
    *,
    anthropic_batch: bool = False,
    model: str | None = None,
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
) -> Path:
    records = load_manifest(artifact_dir)
    revision = _artifact_revision(artifact_dir)
    index_dir = artifact_dir / "indexes" / "pageindex"
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / "index.json"
    expected_meta = {
        "method": "pageindex",
        "artifact_revision": revision,
    }
    if anthropic_batch:
        batch_id = submit_pageindex_batch(
            artifact_dir,
            model=model or batch_model(),
            resume=resume,
        )
        print(
            "Submitted Anthropic Message Batch for PageIndex summaries. "
            f"Batch id: {batch_id}. Re-run without --anthropic-batch after results are materialized."
        )
    if not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("pageindex: index fresh, skipping (use --rebuild-indexes to force)")
        return path

    parts_dir = index_dir / "parts"
    documents: list[dict[str, Any]] = []
    progress = ProgressBar("PageIndex", len(records), enabled=show_progress)
    try:
        for record in records:
            part = _load_pageindex_part(parts_dir, record) if resume else None
            detail = f"resume {record.filename}"
            if part is None:
                part = _build_pageindex_part(artifact_dir, record)
                _write_json_file(_part_path(parts_dir, record.document_id), part, indent=2)
                detail = f"built {record.filename}"
            document = part.get("document")
            if isinstance(document, dict):
                documents.append(document)
            progress.advance(detail=detail)
    except Exception:
        progress.fail()
        raise
    progress.close()

    _write_json_file(path, {"documents": documents}, indent=2)
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(documents),
        },
    )
    return path


def _build_pageindex_part(artifact_dir: Path, record: Any) -> dict[str, Any]:
    text = document_text(artifact_dir, record)
    pages = []
    for page in record.pages:
        page_text = text[page.start_char : page.end_char]
        pages.append(
            {
                "page": page.page,
                "start_char": page.start_char,
                "end_char": page.end_char,
                "title": f"{record.title} / page {page.page}",
                "summary": _page_summary(page_text),
            }
        )
    return {
        "method": "pageindex",
        "document_id": record.document_id,
        "text_sha256": record.text_sha256,
        "document": {
            "document_id": record.document_id,
            "title": record.title,
            "category": record.category,
            "summary": _page_summary(text, max_chars=1200),
            "pages": pages,
        },
    }


def _load_pageindex_part(parts_dir: Path, record: Any) -> dict[str, Any] | None:
    payload = _read_json_file(_part_path(parts_dir, record.document_id))
    if not isinstance(payload, dict):
        return None
    expected = {
        "method": "pageindex",
        "document_id": record.document_id,
        "text_sha256": record.text_sha256,
    }
    if not all(payload.get(key) == value for key, value in expected.items()):
        return None
    return payload if isinstance(payload.get("document"), dict) else None


def build_graphrag_prerequisites(artifact_dir: Path, *, show_progress: bool = False) -> Path:
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
            corpus[f"grid/{target.name}"] = text
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
    return [
        module
        for module in GRAPHRAG_REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    ]


def build_graphrag_index(artifact_dir: Path, *, rebuild: bool = False, show_progress: bool = False) -> None:
    data_dir = build_graphrag_prerequisites(artifact_dir, show_progress=show_progress)
    missing = _missing_graphrag_dependencies()
    if missing:
        raise RuntimeError(
            "GraphRAG Python dependencies are missing in this project environment: "
            f"{', '.join(missing)}. Run `uv sync --extra graphrag` in app/GridAgentCore, "
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
        sys.executable,
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


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    start_char: int
    end_char: int
    text: str
    score: float
    source: str
    section: str = ""


def _dense_cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return numerator / (left_norm * right_norm)


def load_vector_hits(artifact_dir: Path, query: str, *, top_k: int = 8) -> list[SearchHit]:
    path = artifact_dir / "indexes" / "vector" / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing vector index: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    provider = payload.get("provider", "local")
    query_vector = _term_vector(query) if provider == "local" else {}
    query_embedding = (
        _voyage_embeddings([query], input_type="query")[0] if provider == "voyage" else []
    )
    hits = []
    for chunk in payload.get("chunks", []):
        if provider == "voyage":
            score = _dense_cosine(query_embedding, list(chunk.get("embedding") or []))
        else:
            score = _cosine(query_vector, dict(chunk.get("vector") or {}))
        if score > 0:
            hits.append(
                SearchHit(
                    document_id=chunk["document_id"],
                    start_char=int(chunk["start_char"]),
                    end_char=int(chunk["end_char"]),
                    text=str(chunk.get("text") or ""),
                    score=score,
                    source="vector",
                )
            )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]


def load_pageindex_hits(artifact_dir: Path, query: str, *, top_k: int = 8) -> list[SearchHit]:
    path = artifact_dir / "indexes" / "pageindex" / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing PageIndex index: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    query_vector = _term_vector(query)
    hits = []
    for doc in payload.get("documents", []):
        for page in doc.get("pages", []):
            haystack = " ".join([doc.get("title", ""), doc.get("category", ""), page.get("title", ""), page.get("summary", "")])
            score = _cosine(query_vector, _term_vector(haystack))
            if score > 0:
                hits.append(
                    SearchHit(
                        document_id=doc["document_id"],
                        start_char=int(page["start_char"]),
                        end_char=int(page["end_char"]),
                        text=str(page.get("summary") or ""),
                        score=score,
                        source="pageindex",
                        section=str(page.get("title") or ""),
                    )
                )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]


def build_all(
    artifact_dir: Path,
    *,
    methods: list[str],
    anthropic_batch: bool = False,
    resume: bool = True,
    rebuild_indexes: bool = False,
    rebuild_graphrag: bool = False,
    vector_provider: str = "voyage",
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
        print(f"Building vector index for {len(records)} documents...")
        build_vector_index(
            artifact_dir,
            provider=vector_provider,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    if "pageindex" in selected:
        print("Building PageIndex index...")
        build_pageindex(
            artifact_dir,
            anthropic_batch=anthropic_batch,
            resume=resume,
            rebuild=rebuild_indexes,
            show_progress=show_progress,
        )
    if "graphrag" in selected:
        print("Building GraphRAG index with local GridAgentCore graphrag_ms worker...")
        build_graphrag_index(
            artifact_dir,
            rebuild=rebuild_graphrag,
            show_progress=show_progress,
        )
    print(f"Grid index build finished in {time.time() - start:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Grid document indexes.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--methods", default="vector,pageindex,graphrag")
    parser.add_argument("--source-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--anthropic-batch", action="store_true")
    parser.add_argument("--rebuild-indexes", action="store_true")
    parser.add_argument("--rebuild-graphrag", action="store_true")
    parser.add_argument("--no-resume", action="store_true", help="Rebuild per-document index parts.")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars.")
    parser.add_argument("--vector-provider", choices=["voyage", "local"], default="voyage")
    args = parser.parse_args()
    if args.source_dir is not None:
        print("Ignoring --source-dir during indexing; run grid-parse-documents first.")
    rebuild_indexes = args.rebuild_indexes
    if args.force:
        rebuild_indexes = True
        print("Treating --force as --rebuild-indexes during indexing.")
    methods = []
    valid_methods = {"vector", "pageindex", "graphrag"}
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
        show_progress=not args.no_progress,
    )


if __name__ == "__main__":
    main()
