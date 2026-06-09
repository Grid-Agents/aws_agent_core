from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .corpus import document_text, load_manifest
from .indexes import SearchHit, _artifact_revision, _index_is_current, _write_index_meta, _write_json_file
from .models import DocumentRecord, PageRecord
from .progress import ProgressBar
from .settings import (
    colivara_api_base_url,
    colivara_api_key,
    colivara_collection_name,
)


COLIVARA_LOGIC = "colivara_api_v1"
DEFAULT_COLIVARA_TIMEOUT_SECONDS = 120
MAX_PAGE_TEXT_CHARS = 6000
_NON_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")


class ColiVaraClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = (api_key or colivara_api_key()).strip()
        if not self.api_key:
            raise RuntimeError("COLIVARA_API_KEY is required for ColiVara visual retrieval.")
        self.base_url = (base_url or colivara_api_base_url()).rstrip("/")
        self.timeout = timeout or int(
            os.getenv("COLIVARA_TIMEOUT_SECONDS", str(DEFAULT_COLIVARA_TIMEOUT_SECONDS))
        )

    def upsert_document(
        self,
        *,
        name: str,
        collection_name: str,
        document_path: Path,
        metadata: dict[str, Any],
        wait: bool,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "metadata": metadata,
            "collection_name": collection_name,
            "base64": base64.b64encode(document_path.read_bytes()).decode("ascii"),
            "wait": wait,
            "use_proxy": False,
        }
        result = self._request_json("POST", "/v1/documents/upsert-document/", payload)
        return result if isinstance(result, dict) else {"message": result}

    def search(
        self,
        *,
        query: str,
        collection_name: str,
        top_k: int,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "collection_name": collection_name,
            "top_k": top_k,
        }
        result = self._request_json("POST", "/v1/search/", payload)
        if not isinstance(result, dict):
            raise RuntimeError("ColiVara search returned a non-object response.")
        return result

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"ColiVara {method} {path} failed with HTTP {exc.code}: {detail[:600]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ColiVara {method} {path} failed: {exc.reason}") from exc
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("ColiVara returned invalid JSON.") from exc


def colivara_document_name(record: DocumentRecord) -> str:
    stem = Path(record.document_id).stem
    digest = hashlib.sha256(record.document_id.encode("utf-8")).hexdigest()[:10]
    cleaned = _NON_NAME.sub("-", f"{record.category}-{stem}").strip("-").lower()
    return f"{cleaned}-{digest}"[:120]


def build_colivara_index(
    artifact_dir: Path,
    *,
    collection_name: str | None = None,
    wait: bool = True,
    resume: bool = True,
    rebuild: bool = False,
    show_progress: bool = False,
    client: ColiVaraClient | None = None,
) -> Path:
    artifact_dir = artifact_dir.expanduser().resolve()
    records = load_manifest(artifact_dir)
    collection = (collection_name or colivara_collection_name()).strip()
    if not collection:
        raise RuntimeError("COLIVARA_COLLECTION_NAME must not be empty.")
    revision = _artifact_revision(artifact_dir)
    index_dir = artifact_dir / "indexes" / "colivara"
    path = index_dir / "index.json"
    expected_meta = {
        "method": "colivara",
        "logic": COLIVARA_LOGIC,
        "artifact_revision": revision,
        "collection_name": collection,
    }
    if resume and not rebuild and _index_is_current(index_dir, expected=expected_meta):
        print("colivara: sync metadata fresh, skipping (use --rebuild-indexes to force)")
        return path

    api_client = client or ColiVaraClient()
    synced: list[dict[str, Any]] = []
    progress = ProgressBar("Syncing PDFs to ColiVara", len(records), enabled=show_progress)
    try:
        for record in records:
            raw_path = artifact_dir / record.source_path
            if not raw_path.exists():
                raise FileNotFoundError(f"Missing raw PDF for ColiVara sync: {raw_path}")
            document_name = colivara_document_name(record)
            started = time.time()
            response = api_client.upsert_document(
                name=document_name,
                collection_name=collection,
                document_path=raw_path,
                metadata=_document_metadata(record),
                wait=wait,
            )
            synced.append(
                {
                    "document_id": record.document_id,
                    "colivara_document_name": document_name,
                    "title": record.title,
                    "category": record.category,
                    "filename": record.filename,
                    "source_sha256": record.source_sha256,
                    "text_sha256": record.text_sha256,
                    "latency_ms": round((time.time() - started) * 1000),
                    "response_id": response.get("id"),
                    "num_pages": response.get("num_pages"),
                }
            )
            progress.advance(detail=record.filename)
    except Exception:
        progress.fail()
        raise
    progress.close()

    payload = {
        "method": "colivara",
        "logic": COLIVARA_LOGIC,
        "artifact_revision": revision,
        "collection_name": collection,
        "document_count": len(records),
        "documents": synced,
        "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json_file(path, payload, indent=2)
    _write_index_meta(
        index_dir,
        {
            **expected_meta,
            "document_count": len(records),
        },
    )
    return path


def load_colivara_hits(
    artifact_dir: Path,
    query: str,
    *,
    top_k: int = 8,
    client: ColiVaraClient | None = None,
) -> list[SearchHit]:
    artifact_dir = artifact_dir.expanduser().resolve()
    index_payload = _load_index_payload(artifact_dir)
    collection = str(index_payload.get("collection_name") or colivara_collection_name())
    if not collection:
        raise RuntimeError("COLIVARA_COLLECTION_NAME must not be empty.")

    records = load_manifest(artifact_dir)
    by_id = {record.document_id: record for record in records}
    by_colivara_name = {
        str(item.get("colivara_document_name")): str(item.get("document_id"))
        for item in index_payload.get("documents", [])
        if isinstance(item, dict)
    }
    api_client = client or ColiVaraClient()
    output = api_client.search(query=query, collection_name=collection, top_k=top_k)
    results = output.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError("ColiVara search response did not include a result list.")
    hits: list[SearchHit] = []
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    for rank, item in enumerate(results[:top_k], start=1):
        if not isinstance(item, dict):
            continue
        metadata = item.get("document_metadata")
        document_name = str(item.get("document_name") or "")
        document_id = _document_id_from_result(metadata, document_name, by_colivara_name)
        record = by_id.get(document_id or "")
        if record is None:
            continue
        page_number = _optional_int(item.get("page_number"))
        start_char, end_char, page_text = _page_text_for_result(artifact_dir, record, page_number)
        score = _score(item)
        figure = _page_image_payload(
            artifact_dir,
            item,
            query_hash=query_hash,
            rank=rank,
            record=record,
            page_number=page_number,
            score=score,
            collection_name=collection,
        )
        span_text = _span_text(
            query=query,
            item=item,
            record=record,
            page_number=page_number,
            score=score,
            page_text=page_text,
        )
        hits.append(
            SearchHit(
                document_id=record.document_id,
                start_char=start_char,
                end_char=end_char,
                text=span_text,
                score=score,
                source="colivara",
                section="ColiVara visual page match",
                metadata={"figures": [figure], "colivara": _result_metadata(item, collection)}
                if figure
                else {"colivara": _result_metadata(item, collection)},
            )
        )
    return hits


def _document_metadata(record: DocumentRecord) -> dict[str, Any]:
    return {
        "grid_document_id": record.document_id,
        "title": record.title,
        "category": record.category,
        "filename": record.filename,
        "source_path": record.source_path,
        "text_path": record.text_path,
        "source_sha256": record.source_sha256,
        "text_sha256": record.text_sha256,
    }


def _load_index_payload(artifact_dir: Path) -> dict[str, Any]:
    path = artifact_dir / "indexes" / "colivara" / "index.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing ColiVara sync metadata: {path}. "
            "Run `uv run grid-build-indexes --methods colivara` first."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("logic") != COLIVARA_LOGIC:
        raise RuntimeError(f"Invalid ColiVara index metadata: {path}")
    return payload


def _document_id_from_result(
    metadata: Any,
    document_name: str,
    by_colivara_name: dict[str, str],
) -> str:
    if isinstance(metadata, dict):
        document_id = metadata.get("grid_document_id")
        if isinstance(document_id, str) and document_id:
            return document_id
    return by_colivara_name.get(document_name, "")


def _page_text_for_result(
    artifact_dir: Path,
    record: DocumentRecord | None,
    page_number: int | None,
) -> tuple[int, int, str]:
    if record is None:
        return 0, 0, ""
    page = _page_record(record, page_number)
    if page is None:
        return 0, 0, ""
    try:
        text = document_text(artifact_dir, record)
    except OSError:
        return page.start_char, page.end_char, ""
    page_text = text[page.start_char : page.end_char].strip()
    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS].rstrip() + "\n..."
    return page.start_char, page.end_char, page_text


def _page_record(record: DocumentRecord, page_number: int | None) -> PageRecord | None:
    if page_number is None:
        return None
    return next((page for page in record.pages if page.page == page_number), None)


def _page_image_payload(
    artifact_dir: Path,
    item: dict[str, Any],
    *,
    query_hash: str,
    rank: int,
    record: DocumentRecord | None,
    page_number: int | None,
    score: float,
    collection_name: str,
) -> dict[str, Any] | None:
    img_base64 = item.get("img_base64")
    if not isinstance(img_base64, str) or not img_base64.strip():
        return None
    image_bytes = _decode_base64_image(img_base64)
    if not image_bytes:
        return None
    content_type = _detect_image_type(image_bytes)
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    document_label = record.document_id if record else str(item.get("document_name") or "unknown")
    safe_doc = _NON_NAME.sub("-", document_label).strip("-").lower()[:80] or "document"
    page_label = page_number if page_number is not None else rank
    relative_path = Path("colivara_results") / query_hash / f"{safe_doc}-page-{page_label:04d}{extension}"
    image_path = artifact_dir / relative_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(image_bytes)
    figure_id = f"{document_label}#colivara-page-{page_label}"
    return {
        "figure_id": figure_id,
        "page": page_number,
        "description": (
            "Full-page ColiVara visual retrieval result "
            f"from collection {collection_name}; normalized score {score:.3f}."
        ),
        "image_path": relative_path.as_posix(),
        "local_path": str(image_path),
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "filename": image_path.name,
        "content_type": content_type,
        "size_bytes": len(image_bytes),
        "category": "colivara_page",
        "raw_score": item.get("raw_score"),
        "normalized_score": item.get("normalized_score"),
    }


def _decode_base64_image(value: str) -> bytes:
    raw = value.strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return b""


def _detect_image_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _score(item: dict[str, Any]) -> float:
    value = item.get("normalized_score")
    if value is None:
        value = item.get("raw_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _span_text(
    *,
    query: str,
    item: dict[str, Any],
    record: DocumentRecord | None,
    page_number: int | None,
    score: float,
    page_text: str,
) -> str:
    title = record.title if record else str(item.get("document_name") or "Unknown document")
    heading = (
        "ColiVara visual retrieval match using multi-vector late interaction.\n"
        f"Query: {query}\n"
        f"Document: {title}\n"
        f"Page: {page_number or '?'}\n"
        f"Score: {score:.3f}"
    )
    if page_text:
        return f"{heading}\n\nParsed page text:\n{page_text}"
    return f"{heading}\n\nNo parsed page text was available; use the attached page image."


def _result_metadata(item: dict[str, Any], collection_name: str) -> dict[str, Any]:
    return {
        "collection_name": item.get("collection_name") or collection_name,
        "collection_id": item.get("collection_id"),
        "document_name": item.get("document_name"),
        "document_id": item.get("document_id"),
        "page_number": item.get("page_number"),
        "raw_score": item.get("raw_score"),
        "normalized_score": item.get("normalized_score"),
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
