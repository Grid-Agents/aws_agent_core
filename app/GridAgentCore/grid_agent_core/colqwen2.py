from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .corpus import document_text, load_manifest
from .indexes import (
    SearchHit,
    _artifact_revision,
    _index_is_current,
    _write_index_meta,
    _write_json_file,
)
from .models import DocumentRecord, PageRecord
from .progress import ProgressBar
from .settings import (
    DEFAULT_ARTIFACT_DIR,
    colqwen2_endpoint_name,
    colqwen2_image_dpi,
    colqwen2_index_batch_size,
    colqwen2_model_name,
)


COLQWEN2_LOGIC = "aws_sagemaker_colqwen2_multivector_v1"
MAX_PAGE_TEXT_CHARS = 6000
_NON_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")


class SageMakerColQwen2Client:
    def __init__(self, *, endpoint_name: str | None = None, timeout: int | None = None) -> None:
        self.endpoint_name = (endpoint_name or colqwen2_endpoint_name()).strip()
        if not self.endpoint_name:
            raise RuntimeError("COLQWEN2_ENDPOINT_NAME is required for AWS ColQwen2 retrieval.")
        self.timeout = timeout or int(os.getenv("COLQWEN2_TIMEOUT_SECONDS", "300"))
        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
            raise RuntimeError("boto3 is required to call the ColQwen2 SageMaker endpoint.") from exc
        self._runtime = boto3.client(
            "sagemaker-runtime",
            region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            config=Config(read_timeout=self.timeout, connect_timeout=30, retries={"max_attempts": 3}),
        )

    def embed_images(self, image_bytes: list[bytes]) -> list[np.ndarray]:
        if not image_bytes:
            return []
        payload = {
            "task": "embed_images",
            "response_format": "npy",
            "images": [
                {"data_base64": base64.b64encode(item).decode("ascii")}
                for item in image_bytes
            ],
        }
        return self._invoke_embeddings(payload)

    def embed_queries(self, queries: list[str]) -> list[np.ndarray]:
        if not queries:
            return []
        payload = {
            "task": "embed_queries",
            "response_format": "npy",
            "queries": queries,
        }
        return self._invoke_embeddings(payload)

    def _invoke_embeddings(self, payload: dict[str, Any]) -> list[np.ndarray]:
        response = self._runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(payload).encode("utf-8"),
        )
        body = response["Body"].read()
        data = json.loads(body.decode("utf-8"))
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise RuntimeError("ColQwen2 endpoint response did not include embeddings.")
        return [_decode_embedding_payload(item) for item in embeddings]


EmbeddingClient = Any
PageRenderer = Callable[[Path, int, int, Path], bytes]


def build_colqwen2_index(
    artifact_dir: Path,
    *,
    endpoint_name: str | None = None,
    model_name: str | None = None,
    image_dpi: int | None = None,
    batch_size: int | None = None,
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
    client: EmbeddingClient | None = None,
    page_renderer: PageRenderer | None = None,
) -> Path:
    artifact_dir = artifact_dir.expanduser().resolve()
    records = load_manifest(artifact_dir)
    revision = _artifact_revision(artifact_dir)
    model = (model_name or colqwen2_model_name()).strip()
    dpi = image_dpi or colqwen2_image_dpi()
    index_dir = artifact_dir / "indexes" / "colqwen2"
    path = index_dir / "index.json"
    dtype = os.getenv("COLQWEN2_INDEX_DTYPE", "float16").strip() or "float16"
    expected_meta = {
        "method": "colqwen2",
        "logic": COLQWEN2_LOGIC,
        "artifact_revision": revision,
        "model_name": model,
        "image_dpi": dpi,
        "embedding_dtype": dtype,
    }
    if resume and not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("colqwen2: index fresh, skipping (use --rebuild-indexes to force)")
        return path

    api_client = client or SageMakerColQwen2Client(endpoint_name=endpoint_name)
    renderer = page_renderer or _render_pdf_page
    page_count = sum(len(record.pages) for record in records)
    progress = ProgressBar("Building AWS ColQwen2 visual index", page_count, enabled=show_progress)
    pages: list[dict[str, Any]] = []
    pending: list[tuple[DocumentRecord, PageRecord, Path, bytes]] = []
    effective_batch_size = max(1, batch_size or colqwen2_index_batch_size())

    def flush_pending() -> None:
        nonlocal pending
        if not pending:
            return
        batch_detail = ", ".join(f"{item[0].filename} p{item[1].page}" for item in pending)
        started = time.perf_counter()
        print(f"colqwen2: embedding {len(pending)} page image(s): {batch_detail}", flush=True)
        embeddings = _embed_images_adaptive(api_client, pending)
        print(
            f"colqwen2: embedded {len(pending)} page image(s) in {time.perf_counter() - started:.1f}s",
            flush=True,
        )
        if len(embeddings) != len(pending):
            raise RuntimeError(
                "ColQwen2 endpoint returned "
                f"{len(embeddings)} embeddings for {len(pending)} page images."
            )
        for (record, page, image_path, _image_bytes), embedding in zip(pending, embeddings):
            relative_embedding_path = _embedding_relative_path(record, page.page)
            embedding_path = artifact_dir / relative_embedding_path
            _write_embedding(embedding_path, embedding, dtype=dtype)
            pages.append(
                {
                    "document_id": record.document_id,
                    "title": record.title,
                    "category": record.category,
                    "filename": record.filename,
                    "page": page.page,
                    "start_char": page.start_char,
                    "end_char": page.end_char,
                    "image_path": image_path.relative_to(artifact_dir).as_posix(),
                    "embedding_path": relative_embedding_path.as_posix(),
                    "embedding_shape": list(np.asarray(embedding).shape),
                }
            )
            progress.advance(detail=f"{record.filename} p{page.page}")
        pending = []

    try:
        for record in records:
            raw_path = artifact_dir / record.source_path
            if not raw_path.exists():
                raise FileNotFoundError(f"Missing raw PDF for ColQwen2 indexing: {raw_path}")
            for page in record.pages:
                image_path = artifact_dir / _page_image_relative_path(record, page.page)
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_bytes = renderer(raw_path, page.page, dpi, image_path)
                pending.append((record, page, image_path, image_bytes))
                if len(pending) >= effective_batch_size:
                    flush_pending()
        flush_pending()
    except Exception:
        progress.fail()
        raise
    progress.close()

    payload = {
        "method": "colqwen2",
        "logic": COLQWEN2_LOGIC,
        "artifact_revision": revision,
        "model_name": model,
        "endpoint_name": (endpoint_name or colqwen2_endpoint_name()).strip(),
        "image_dpi": dpi,
        "embedding_dtype": dtype,
        "document_count": len(records),
        "page_count": len(pages),
        "pages": pages,
        "documents": [
            {
                "document_id": record.document_id,
                "title": record.title,
                "category": record.category,
                "filename": record.filename,
                "source_sha256": record.source_sha256,
                "text_sha256": record.text_sha256,
            }
            for record in records
        ],
        "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json_file(path, payload, indent=2)
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(records),
            "page_count": len(pages),
        },
    )
    return path


def _embed_images_adaptive(
    api_client: EmbeddingClient,
    batch: list[tuple[DocumentRecord, PageRecord, Path, bytes]],
) -> list[np.ndarray]:
    try:
        return api_client.embed_images([item[3] for item in batch])
    except Exception as exc:
        if len(batch) > 1 and _is_sagemaker_timeout(exc):
            midpoint = len(batch) // 2
            print(
                "colqwen2: SageMaker timed out on "
                f"{len(batch)} page images; retrying as smaller batches",
                flush=True,
            )
            return _embed_images_adaptive(api_client, batch[:midpoint]) + _embed_images_adaptive(
                api_client, batch[midpoint:]
            )
        if _is_sagemaker_timeout(exc):
            record, page, _image_path, image_bytes = batch[0]
            raise RuntimeError(
                "SageMaker timed out embedding a single ColQwen2 page image "
                f"({record.filename} p{page.page}, {len(image_bytes)} bytes). "
                "Lower COLQWEN2_MAX_VISUAL_TOKENS or COLQWEN2_IMAGE_DPI, "
                "or use a larger SageMaker GPU instance."
            ) from exc
        raise


def _is_sagemaker_timeout(exc: Exception) -> bool:
    message = str(exc).lower()
    return "timed out while waiting for a response from container" in message or (
        "modelerror" in type(exc).__name__.lower() and "timed out" in message
    )


def load_colqwen2_hits(
    artifact_dir: Path,
    query: str,
    *,
    top_k: int = 8,
    client: EmbeddingClient | None = None,
) -> list[SearchHit]:
    artifact_dir = artifact_dir.expanduser().resolve()
    index_payload = _load_index_payload(artifact_dir)
    records = load_manifest(artifact_dir)
    by_id = {record.document_id: record for record in records}
    api_client = client or SageMakerColQwen2Client(
        endpoint_name=str(index_payload.get("endpoint_name") or colqwen2_endpoint_name())
    )
    query_embeddings = api_client.embed_queries([query])
    if not query_embeddings:
        return []
    query_embedding = _as_2d_float32(query_embeddings[0])
    scored: list[tuple[float, dict[str, Any]]] = []
    for page in index_payload.get("pages", []):
        if not isinstance(page, dict):
            continue
        embedding_path = artifact_dir / str(page.get("embedding_path") or "")
        if not embedding_path.exists():
            continue
        document_embedding = _read_embedding(embedding_path)
        score = late_interaction_score(query_embedding, document_embedding)
        scored.append((score, page))
    scored.sort(key=lambda item: item[0], reverse=True)

    hits: list[SearchHit] = []
    for score, page in scored[:top_k]:
        document_id = str(page.get("document_id") or "")
        record = by_id.get(document_id)
        if record is None:
            continue
        page_number = _optional_int(page.get("page"))
        start_char = _optional_int(page.get("start_char")) or 0
        end_char = _optional_int(page.get("end_char")) or start_char
        page_text = _page_text(artifact_dir, record, start_char, end_char)
        figure = _page_image_payload(artifact_dir, page, record=record, score=score)
        hits.append(
            SearchHit(
                document_id=record.document_id,
                start_char=start_char,
                end_char=end_char,
                text=_span_text(
                    query=query,
                    record=record,
                    page_number=page_number,
                    score=score,
                    page_text=page_text,
                    model_name=str(index_payload.get("model_name") or colqwen2_model_name()),
                ),
                score=score,
                source="colqwen2",
                section="AWS ColQwen2 visual page match",
                metadata={"figures": [figure], "colqwen2": _result_metadata(page, index_payload)}
                if figure
                else {"colqwen2": _result_metadata(page, index_payload)},
            )
        )
    return hits


def late_interaction_score(query_embedding: np.ndarray, document_embedding: np.ndarray) -> float:
    query_vectors = _as_2d_float32(query_embedding)
    document_vectors = _as_2d_float32(document_embedding)
    if query_vectors.size == 0 or document_vectors.size == 0:
        return 0.0
    similarities = query_vectors @ document_vectors.T
    return float(np.max(similarities, axis=1).sum())


def _render_pdf_page(raw_path: Path, page_number: int, dpi: int, image_path: Path) -> bytes:
    try:
        import fitz
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyMuPDF and Pillow are required to render PDF pages for ColQwen2 indexing. "
            "Run `uv sync --extra build` in app/GridAgentCore."
        ) from exc
    with fitz.open(raw_path) as document:
        page_index = page_number - 1
        if page_index < 0 or page_index >= document.page_count:
            raise RuntimeError(f"{raw_path} does not have page {page_number}.")
        page = document.load_page(page_index)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=int(os.getenv("COLQWEN2_PAGE_JPEG_QUALITY", "88")))
    data = buffer.getvalue()
    image_path.write_bytes(data)
    return data


def _decode_embedding_payload(item: Any) -> np.ndarray:
    if isinstance(item, dict):
        encoded = item.get("data_base64") or item.get("npy_base64")
        if isinstance(encoded, str) and encoded:
            return np.load(io.BytesIO(base64.b64decode(encoded)), allow_pickle=False)
        if "embedding" in item:
            return np.asarray(item["embedding"])
        if "values" in item:
            return np.asarray(item["values"])
    return np.asarray(item)


def _write_embedding(path: Path, embedding: np.ndarray, *, dtype: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    array = _as_2d_float32(np.asarray(embedding)).astype(dtype)
    with temp_path.open("wb") as handle:
        np.save(handle, array, allow_pickle=False)
    temp_path.replace(path)


def _read_embedding(path: Path) -> np.ndarray:
    return _as_2d_float32(np.load(path, allow_pickle=False))


def _as_2d_float32(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2:
        raise RuntimeError(f"Expected a 2-D multi-vector embedding, got shape {array.shape}.")
    return array


def _load_index_payload(artifact_dir: Path) -> dict[str, Any]:
    path = artifact_dir / "indexes" / "colqwen2" / "index.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing AWS ColQwen2 visual index: {path}. "
            "Run `python scripts/build_colqwen2_index.py` or "
            "`uv run grid-build-indexes --methods colqwen2` first."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("logic") != COLQWEN2_LOGIC:
        raise RuntimeError(f"Invalid AWS ColQwen2 index metadata: {path}")
    return payload


def _page_text(artifact_dir: Path, record: DocumentRecord, start_char: int, end_char: int) -> str:
    try:
        text = document_text(artifact_dir, record)
    except OSError:
        return ""
    page_text = text[start_char:end_char].strip()
    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS].rstrip() + "\n..."
    return page_text


def _page_image_payload(
    artifact_dir: Path,
    page: dict[str, Any],
    *,
    record: DocumentRecord,
    score: float,
) -> dict[str, Any] | None:
    image_path_value = str(page.get("image_path") or "")
    if not image_path_value:
        return None
    local_path = artifact_dir / image_path_value
    if not local_path.exists():
        return None
    page_number = _optional_int(page.get("page"))
    content_type = mimetypes.guess_type(local_path.name)[0] or "image/jpeg"
    return {
        "figure_id": f"{record.document_id}#colqwen2-page-{page_number or '?'}",
        "page": page_number,
        "description": (
            "Full-page AWS ColQwen2 visual retrieval result "
            f"from self-hosted SageMaker inference; late-interaction score {score:.3f}."
        ),
        "image_path": image_path_value,
        "local_path": str(local_path),
        "image_sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
        "filename": local_path.name,
        "content_type": content_type,
        "size_bytes": local_path.stat().st_size,
        "category": "colqwen2_page",
        "score": score,
    }


def _span_text(
    *,
    query: str,
    record: DocumentRecord,
    page_number: int | None,
    score: float,
    page_text: str,
    model_name: str,
) -> str:
    heading = (
        "AWS ColQwen2 visual retrieval match using page-image multi-vector embeddings.\n"
        f"Model: {model_name}\n"
        f"Query: {query}\n"
        f"Document: {record.title}\n"
        f"Page: {page_number or '?'}\n"
        f"Late-interaction score: {score:.3f}"
    )
    if page_text:
        return f"{heading}\n\nParsed page text:\n{page_text}"
    return f"{heading}\n\nNo parsed page text was available; use the attached page image."


def _result_metadata(page: dict[str, Any], index_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint_name": index_payload.get("endpoint_name"),
        "model_name": index_payload.get("model_name"),
        "image_dpi": index_payload.get("image_dpi"),
        "document_id": page.get("document_id"),
        "page": page.get("page"),
        "image_path": page.get("image_path"),
        "embedding_path": page.get("embedding_path"),
        "embedding_shape": page.get("embedding_shape"),
    }


def _page_image_relative_path(record: DocumentRecord, page_number: int) -> Path:
    return Path("colqwen2_pages") / _document_slug(record) / f"page-{page_number:04d}.jpg"


def _embedding_relative_path(record: DocumentRecord, page_number: int) -> Path:
    return Path("indexes") / "colqwen2" / "embeddings" / _document_slug(record) / f"page-{page_number:04d}.npy"


def _document_slug(record: DocumentRecord) -> str:
    stem = Path(record.document_id).stem
    digest = hashlib.sha256(record.document_id.encode("utf-8")).hexdigest()[:10]
    cleaned = _NON_NAME.sub("-", f"{record.category}-{stem}").strip("-").lower()
    return f"{cleaned}-{digest}"[:120] or digest


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AWS ColQwen2 multi-vector page indexes.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--endpoint-name", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--image-dpi", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--rebuild-indexes", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()
    build_colqwen2_index(
        args.artifact_dir,
        endpoint_name=args.endpoint_name,
        model_name=args.model_name,
        image_dpi=args.image_dpi,
        batch_size=args.batch_size,
        resume=not args.no_resume,
        rebuild=args.rebuild_indexes,
        show_progress=not args.no_progress,
    )


if __name__ == "__main__":
    main()
