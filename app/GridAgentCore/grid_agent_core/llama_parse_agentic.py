from __future__ import annotations

import os
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from .progress import ProgressBar


CREDIT_RATE_USD = 0.00125
CREDITS_PER_PAGE = 10
DEFAULT_MAX_PAGES_PER_JOB = 50
DEFAULT_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class ParsedPage:
    page: int
    markdown: str


@dataclass(frozen=True)
class LlamaParseResult:
    pages: list[ParsedPage]
    raw_payload: dict[str, Any]


def parse_pdf_agentic(
    path: Path,
    *,
    timeout: float | None = None,
    max_pages_per_job: int | None = None,
    show_progress: bool = False,
    cache_dir: Path | None = None,
    target_page_range: tuple[int, int] | None = None,
) -> LlamaParseResult:
    client = _llama_client()
    max_pages = max_pages_per_job or int(
        os.getenv("LLAMAPARSE_MAX_PAGES_PER_JOB", str(DEFAULT_MAX_PAGES_PER_JOB))
    )
    if max_pages <= 0:
        raise ValueError("LLAMAPARSE_MAX_PAGES_PER_JOB must be greater than zero.")
    timeout_seconds = timeout or float(
        os.getenv("LLAMAPARSE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    )

    page_count = _pdf_page_count(path)
    if target_page_range is not None:
        return _parse_target_page_range_pdf(
            client,
            path,
            target_page_range=target_page_range,
            page_count=page_count,
            timeout=timeout_seconds,
            cache_dir=cache_dir,
        )

    if page_count is None or page_count <= max_pages:
        payload = _parse_pdf_job_payload(client, path, timeout=timeout_seconds)
        return LlamaParseResult(
            pages=_pages_from_payload(payload),
            raw_payload=payload,
        )

    return _parse_partitioned_pdf(
        client,
        path,
        page_count=page_count,
        max_pages_per_job=max_pages,
        timeout=timeout_seconds,
        show_progress=show_progress,
        cache_dir=cache_dir,
    )


def _llama_client() -> Any:
    try:
        from llama_cloud import LlamaCloud
    except ImportError as exc:
        raise RuntimeError(
            "llama-cloud is required for --parser llamaparse-agentic. "
            "Run `uv sync` in app/GridAgentCore after updating dependencies."
        ) from exc

    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise RuntimeError("LLAMA_CLOUD_API_KEY is required for --parser llamaparse-agentic.")

    return LlamaCloud(api_key=api_key)


def _parse_pdf_job_payload(client: Any, path: Path, *, timeout: float) -> dict[str, Any]:
    job = client.parsing.create(
        upload_file=str(path),
        tier="agentic",
        version="latest",
        disable_cache=True,
    )
    client.parsing.wait_for_completion(job.id, timeout=timeout)
    result = client.parsing.get(
        job.id,
        expand=[
            "items",
            "text",
            "metadata",
            "debug_logs",
        ],
    )
    payload = result.model_dump(mode="json", by_alias=True)
    _attach_cost_metadata(payload)
    return payload


def _parse_partitioned_pdf(
    client: Any,
    path: Path,
    *,
    page_count: int,
    max_pages_per_job: int,
    timeout: float,
    show_progress: bool,
    cache_dir: Path | None,
) -> LlamaParseResult:
    ranges = [
        (start, min(start + max_pages_per_job - 1, page_count))
        for start in range(1, page_count + 1, max_pages_per_job)
    ]
    progress = ProgressBar(
        f"LlamaParse partitions {path.name}",
        len(ranges),
        enabled=show_progress,
    )
    pages: list[ParsedPage] = []
    partitions: list[dict[str, Any]] = []
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="grid-llamaparse-") as temp_root:
            temp_dir = Path(temp_root)
            for start_page, end_page in ranges:
                payload = _read_partition_cache(cache_dir, start_page, end_page)
                if payload is None:
                    partition_path = temp_dir / (
                        f"{path.stem}.pages-{start_page}-{end_page}.pdf"
                    )
                    _write_pdf_partition(
                        path,
                        partition_path,
                        start_page=start_page,
                        end_page=end_page,
                    )
                    try:
                        payload = _parse_pdf_job_payload(client, partition_path, timeout=timeout)
                    except Exception as exc:
                        progress.fail(detail=f"failed pages {start_page}-{end_page}")
                        raise RuntimeError(
                            f"LlamaParse failed for {path.name} pages {start_page}-{end_page}: {exc}"
                        ) from exc
                    _write_partition_cache(cache_dir, start_page, end_page, payload)
                payload["source_page_start"] = start_page
                payload["source_page_end"] = end_page
                payload["page_offset"] = start_page - 1
                partitions.append(payload)
                for page in _pages_from_payload(payload):
                    pages.append(
                        ParsedPage(
                            page=page.page + start_page - 1,
                            markdown=page.markdown,
                        )
                    )
                progress.advance(detail=f"pages {start_page}-{end_page}")
    except Exception:
        raise
    else:
        progress.close()

    raw_payload: dict[str, Any] = {
        "job_id": "partitioned",
        "source_file": path.name,
        "num_pages": page_count,
        "partition_count": len(partitions),
        "max_pages_per_job": max_pages_per_job,
        "partitions": partitions,
    }
    _attach_cost_metadata(raw_payload)
    return LlamaParseResult(pages=pages, raw_payload=raw_payload)


def _parse_target_page_range_pdf(
    client: Any,
    path: Path,
    *,
    target_page_range: tuple[int, int],
    page_count: int | None,
    timeout: float,
    cache_dir: Path | None,
) -> LlamaParseResult:
    start_page, end_page = target_page_range
    if start_page <= 0 or end_page < start_page:
        raise ValueError("target_page_range must be a positive inclusive range.")
    if page_count is not None and end_page > page_count:
        raise ValueError(
            f"target_page_range {start_page}-{end_page} exceeds {path.name} page count {page_count}."
        )

    payload = _read_partition_cache(cache_dir, start_page, end_page)
    if payload is None:
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="grid-llamaparse-smoke-") as temp_root:
            partition_path = Path(temp_root) / f"{path.stem}.pages-{start_page}-{end_page}.pdf"
            _write_pdf_partition(
                path,
                partition_path,
                start_page=start_page,
                end_page=end_page,
            )
            payload = _parse_pdf_job_payload(client, partition_path, timeout=timeout)
            _write_partition_cache(cache_dir, start_page, end_page, payload)

    payload["source_page_start"] = start_page
    payload["source_page_end"] = end_page
    payload["page_offset"] = start_page - 1
    payload["target_page_range"] = f"{start_page}-{end_page}"
    pages = [
        ParsedPage(page=page.page + start_page - 1, markdown=page.markdown)
        for page in _pages_from_payload(payload)
    ]
    return LlamaParseResult(pages=pages, raw_payload=payload)


def _read_partition_cache(
    cache_dir: Path | None,
    start_page: int,
    end_page: int,
) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"pages-{start_page}-{end_page}.raw.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not payload_matches_parsebench_agentic(payload):
        return None
    return payload


def _write_partition_cache(
    cache_dir: Path | None,
    start_page: int,
    end_page: int,
    payload: dict[str, Any],
) -> None:
    if cache_dir is None:
        return
    path = cache_dir / f"pages-{start_page}-{end_page}.raw.json"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _pdf_page_count(path: Path) -> int | None:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def _write_pdf_partition(
    source_path: Path,
    target_path: Path,
    *,
    start_page: int,
    end_page: int,
) -> None:
    reader = PdfReader(str(source_path))
    writer = PdfWriter()
    for page_index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[page_index])
    with target_path.open("wb") as handle:
        writer.write(handle)


def _attach_cost_metadata(payload: dict[str, Any]) -> None:
    pages = _page_count(payload)
    if pages <= 0:
        return
    credits = pages * CREDITS_PER_PAGE
    payload.setdefault("num_pages", pages)
    payload.setdefault("credits_used", credits)
    payload.setdefault("cost_usd", credits * CREDIT_RATE_USD)
    payload.setdefault("cost_per_page_usd", (credits * CREDIT_RATE_USD) / pages)
    job = payload.get("job")
    if isinstance(job, dict):
        job_id = job.get("id")
        if isinstance(job_id, str) and job_id:
            payload.setdefault("job_id", job_id)


def _page_count(payload: dict[str, Any]) -> int:
    existing = payload.get("num_pages")
    if isinstance(existing, (int, float)) and existing > 0:
        return int(existing)
    pages = _pages_from_payload(payload)
    return len(pages)


def _pages_from_payload(payload: dict[str, Any]) -> list[ParsedPage]:
    normalized = _normalized_pages(payload.get("pages"))
    if normalized:
        return normalized

    page_payloads = _parsebench_pages_from_sdk_payload(payload)
    if page_payloads:
        return [
            ParsedPage(
                page=_page_number(page_payload, index),
                markdown=_string_value(page_payload, ("md", "text")).strip(),
            )
            for index, page_payload in enumerate(page_payloads, start=1)
        ]

    fallback = _string_value(payload, ("markdown", "md", "text"))
    return [ParsedPage(page=1, markdown=fallback.strip())] if fallback.strip() else []


def payload_matches_parsebench_agentic(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("grid_llamaparse_image_extraction") is True:
        return False
    partitions = payload.get("partitions")
    if isinstance(partitions, list):
        return all(
            isinstance(partition, dict) and payload_matches_parsebench_agentic(partition)
            for partition in partitions
        )
    for key in ("images_content_metadata", "markdown", "markdown_full"):
        value = payload.get(key)
        if value not in (None, {}, []):
            return False
    return True


def _parsebench_pages_from_sdk_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items_pages = _section_pages(payload.get("items"))
    text_by_page = _text_pages(payload.get("text"))
    metadata_by_page = _metadata_pages(payload.get("metadata"))
    if not items_pages and not text_by_page and not metadata_by_page:
        return []

    total_pages = max(len(items_pages), len(text_by_page), len(metadata_by_page), 1)
    pages: list[dict[str, Any]] = []
    for page_number in range(1, total_pages + 1):
        page_data: dict[str, Any] = {"page": page_number}
        items_page = items_pages[page_number - 1] if page_number - 1 < len(items_pages) else None
        text_fallback = text_by_page.get(page_number, "")
        metadata_page = metadata_by_page.get(page_number)
        orientation = (
            metadata_page.get("original_orientation_angle")
            if isinstance(metadata_page, dict)
            else None
        )

        if not _is_structured_items_page(items_page):
            if text_fallback:
                page_data["text"] = text_fallback
            if orientation is not None:
                page_data["original_orientation_angle"] = orientation
            pages.append(page_data)
            continue

        (
            item_markdowns,
            item_texts,
            inferred_headers,
            inferred_footers,
        ) = _parsebench_flatten_items(items_page.get("items"))
        if item_markdowns:
            page_data["md"] = "\n\n".join(item_markdowns)
        if item_texts:
            page_data["text"] = "\n\n".join(item_texts)
        if inferred_headers:
            page_data["pageHeaderMarkdown"] = "\n\n".join(inferred_headers)
        if inferred_footers:
            page_data["pageFooterMarkdown"] = "\n\n".join(inferred_footers)
        if "text" not in page_data and text_fallback:
            page_data["text"] = text_fallback
        if orientation is not None:
            page_data["original_orientation_angle"] = orientation
        pages.append(page_data)
    return pages


def _normalized_pages(value: Any) -> list[ParsedPage]:
    if not isinstance(value, list):
        return []
    pages: list[ParsedPage] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        page = _page_number(item, index)
        markdown = _string_value(item, ("md", "markdown", "text"))
        if markdown.strip():
            pages.append(ParsedPage(page=page, markdown=markdown.strip()))
    return pages


def _text_pages(value: Any) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    pages = value.get("pages")
    if not isinstance(pages, list):
        return {}
    results: dict[int, str] = {}
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        page_number = _page_number(page, index)
        text = _string_value(page, ("text", "md", "markdown"))
        if text.strip():
            results[page_number] = text.strip()
    return results


def _section_pages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    pages = value.get("pages")
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _metadata_pages(value: Any) -> dict[int, dict[str, Any]]:
    pages = _section_pages(value)
    results: dict[int, dict[str, Any]] = {}
    for index, page in enumerate(pages, start=1):
        results[_page_number(page, index)] = page
    return results


def _is_structured_items_page(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("success", True) is not False
        and isinstance(value.get("items"), list)
    )


def _parsebench_flatten_items(value: Any) -> tuple[list[str], list[str], list[str], list[str]]:
    item_markdowns: list[str] = []
    item_texts: list[str] = []
    header_markdowns: list[str] = []
    footer_markdowns: list[str] = []

    if isinstance(value, list):
        for item in value:
            child_mds, child_texts, child_headers, child_footers = _parsebench_flatten_items(item)
            item_markdowns.extend(child_mds)
            item_texts.extend(child_texts)
            header_markdowns.extend(child_headers)
            footer_markdowns.extend(child_footers)
        return item_markdowns, item_texts, header_markdowns, footer_markdowns

    if not isinstance(value, dict):
        return item_markdowns, item_texts, header_markdowns, footer_markdowns

    item_type = _string_value(value, ("type",))
    item_md = _string_value(value, ("md",))
    if item_type in {"list", "header", "footer"}:
        if item_md:
            item_markdowns.append(item_md)
            if item_type == "header":
                header_markdowns.append(item_md)
            elif item_type == "footer":
                footer_markdowns.append(item_md)
        child_mds, child_texts, child_headers, child_footers = _parsebench_flatten_items(
            value.get("items")
        )
        item_markdowns.extend(child_mds)
        item_texts.extend(child_texts)
        header_markdowns.extend(child_headers)
        footer_markdowns.extend(child_footers)
        return item_markdowns, item_texts, header_markdowns, footer_markdowns

    if item_type == "table":
        table_content = _string_value(value, ("html",)) or item_md
        if table_content:
            item_markdowns.append(table_content)
    elif item_type == "link":
        link_text = _string_value(value, ("text",))
        if link_text:
            item_markdowns.append(link_text)
    elif item_md:
        item_markdowns.append(item_md)

    if item_type in {"text", "heading", "code"}:
        item_value = _string_value(value, ("value",))
        if item_value:
            item_texts.append(item_value)

    return item_markdowns, item_texts, header_markdowns, footer_markdowns


def _page_number(page: dict[str, Any], fallback: int) -> int:
    for key in ("page", "page_number", "pageNumber"):
        value = page.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return fallback


def _string_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
