from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from .models import FigureRecord, PageRecord
from .progress import ProgressBar, log_event
from .settings import model_id


DEFAULT_RENDER_DPI = 150
MAX_RENDER_WIDTH = 1600
DEFAULT_VLM_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 2.0
DEFAULT_VLM_CONCURRENCY = 4
DEFAULT_MAX_FIGURE_CANDIDATES_PER_PAGE = 4
VISUAL_DESCRIPTION_MARKER = "### Figure context"
VISUAL_CACHE_VERSION = 3
MIN_CANDIDATE_AREA_RATIO = 0.006
MAX_CANDIDATE_AREA_RATIO = 0.82
HEADER_FOOTER_MARGIN_RATIO = 0.055
LOCAL_DRAWING_CLUSTER_MARGIN_PT = 18.0
TEXT_LABEL_EXPANSION_MARGIN_PT = 20.0
NEARBY_TEXT_MARGIN_PT = 72.0
MAX_NEARBY_TEXT_CHARS = 1800
MAX_CURRENT_PAGE_CONTEXT_CHARS = 3600
MAX_NEIGHBOR_PAGE_CONTEXT_CHARS = 1000
MIN_RENDERED_NON_WHITE_RATIO = 0.0025
MAX_RENDERED_DARK_RATIO = 0.84


@dataclass(frozen=True)
class VisualArtifact:
    page: int
    description: str
    image_path: str
    image_sha256: str
    filename: str
    content_type: str
    size_bytes: int
    category: str = "figure_crop"
    bbox: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FigureCandidate:
    page: int
    index: int
    rect: tuple[float, float, float, float]
    bbox: dict[str, Any]
    source: str
    confidence: float | None = None
    image_name: str | None = None
    nearby_text: str = ""


@dataclass(frozen=True)
class _PageEnrichmentResult:
    index: int
    page_number: int
    markdown: str
    artifacts: list[VisualArtifact]
    detail: str


class VisionDescriber(Protocol):
    def describe_page(self, *, image_bytes: bytes, page_number: int, page_markdown: str) -> str:
        ...


class AnthropicVisionDescriber:
    def __init__(self, *, model: str | None = None, region: str | None = None) -> None:
        try:
            import anthropic
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
            raise RuntimeError("anthropic is required for multimodal enrichment.") from exc
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for --multimodal-enrich. "
                "VLM enrichment uses the direct Anthropic API."
            )
        self.model = _anthropic_model_id(model or os.getenv("GRID_VLM_MODEL") or model_id())
        self.client = anthropic.Anthropic(api_key=api_key)
        configured_max_tokens = _resolve_positive_int(
            None,
            env_name="GRID_VLM_MAX_OUTPUT_TOKENS",
            default=DEFAULT_MAX_OUTPUT_TOKENS,
        )
        self.max_tokens = min(
            _anthropic_model_max_tokens(self.client, self.model),
            configured_max_tokens,
        )
        self.max_retries = int(os.getenv("GRID_VLM_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
        self.retry_base_seconds = float(
            os.getenv("GRID_VLM_RETRY_BASE_SECONDS", str(DEFAULT_RETRY_BASE_SECONDS))
        )
        self.cancel_event: threading.Event | None = None

    def set_cancel_event(self, cancel_event: threading.Event | None) -> None:
        self.cancel_event = cancel_event

    def describe_page(self, *, image_bytes: bytes, page_number: int, page_markdown: str) -> str:
        prompt = _description_prompt(page_number=page_number, page_markdown=page_markdown)
        response = None
        cancel_event = getattr(self, "cancel_event", None)
        for attempt in range(self.max_retries + 1):
            _raise_if_cancelled(cancel_event)
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": base64.b64encode(image_bytes).decode("ascii"),
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    temperature=0,
                )
                break
            except Exception as exc:
                if attempt >= self.max_retries or not _is_retryable_api_error(exc):
                    raise
                delay = self.retry_base_seconds * (2**attempt) + random.uniform(0, 0.5)
                log_event(
                    f"page {page_number}: Anthropic retry {attempt + 1}/{self.max_retries} "
                    f"in {delay:.1f}s ({type(exc).__name__})",
                    label="vlm",
                )
                if cancel_event is None:
                    time.sleep(delay)
                elif cancel_event.wait(delay):
                    _raise_if_cancelled(cancel_event)
        if response is None:
            return ""
        return _response_text(response)


def multimodal_enrichment_enabled(value: bool | None = None) -> bool:
    if value is not None:
        return value
    return os.getenv("GRID_MULTIMODAL_ENRICH", "").strip().lower() in {"1", "true", "yes", "on"}


def enrich_page_markdown_with_visuals(
    pdf_path: Path,
    *,
    parsed_pages: list[tuple[int, str]],
    artifact_dir: Path,
    document_key: str,
    raw_payload: dict[str, Any] | None = None,
    describer: VisionDescriber | None = None,
    render_dpi: int | None = None,
    max_pages: int | None = None,
    cache_dir: Path | None = None,
    show_progress: bool = False,
    vlm_concurrency: int | None = None,
    cancel_event: threading.Event | None = None,
    vlm_limiter: threading.Semaphore | None = None,
) -> tuple[list[tuple[int, str]], list[VisualArtifact]]:
    if not parsed_pages:
        return parsed_pages, []

    describer = describer or AnthropicVisionDescriber()
    cancel_event = cancel_event or threading.Event()
    if hasattr(describer, "set_cancel_event"):
        describer.set_cancel_event(cancel_event)
    dpi = render_dpi or int(os.getenv("GRID_VLM_RENDER_DPI", str(DEFAULT_RENDER_DPI)))
    page_limit = max_pages if max_pages is not None else len(parsed_pages)
    pages_to_process = max(0, min(page_limit, len(parsed_pages)))
    workers = _resolve_positive_int(
        vlm_concurrency,
        env_name="GRID_VLM_CONCURRENCY",
        default=DEFAULT_VLM_CONCURRENCY,
    )
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    if show_progress:
        log_event(
            f"document={document_key} pages={pages_to_process} dpi={dpi} "
            f"workers={workers} cache={cache_dir if cache_dir is not None else 'disabled'}",
            label="vlm",
        )
    progress = ProgressBar(
        f"VLM visual enrichment {document_key}",
        pages_to_process,
        enabled=show_progress,
    )

    if pages_to_process == 0:
        progress.close()
        return parsed_pages, []

    page_contexts = _document_context_by_page(parsed_pages, document_key=document_key)
    results: list[_PageEnrichmentResult | None] = [None] * len(parsed_pages)
    for index, (page_number, markdown) in enumerate(parsed_pages):
        if index >= pages_to_process:
            results[index] = _PageEnrichmentResult(
                index=index,
                page_number=page_number,
                markdown=markdown,
                artifacts=[],
                detail=f"page {page_number} unchanged",
            )

    executor = ThreadPoolExecutor(max_workers=min(workers, pages_to_process))
    futures = [
        executor.submit(
            _enrich_one_page,
            index=index,
            page_number=page_number,
            markdown=markdown,
            pdf_path=pdf_path,
            artifact_dir=artifact_dir,
            document_key=document_key,
            raw_payload=raw_payload,
            page_context=page_contexts.get(page_number, markdown),
            describer=describer,
            dpi=dpi,
            cache_dir=cache_dir,
            cancel_event=cancel_event,
            vlm_limiter=vlm_limiter,
        )
        for index, (page_number, markdown) in enumerate(parsed_pages[:pages_to_process])
    ]
    try:
        for future in as_completed(futures):
            result = future.result()
            _raise_if_cancelled(cancel_event)
            results[result.index] = result
            progress.advance(detail=result.detail)
        missing_pages = [
            str(parsed_pages[index][0])
            for index, result in enumerate(results)
            if result is None
        ]
        if missing_pages:
            raise RuntimeError(
                "VLM visual enrichment did not produce results for page(s): "
                + ", ".join(missing_pages)
            )
    except BaseException as exc:
        cancel_event.set()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        progress.fail(detail="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
        raise
    else:
        executor.shutdown()
    progress.close()

    enriched_pages = [
        (result.page_number, result.markdown)
        for result in results
        if result is not None
    ]
    artifacts = [
        artifact
        for result in results
        if result is not None
        for artifact in result.artifacts
    ]
    return enriched_pages, artifacts


def _enrich_one_page(
    *,
    index: int,
    page_number: int,
    markdown: str,
    pdf_path: Path,
    artifact_dir: Path,
    document_key: str,
    raw_payload: dict[str, Any] | None,
    page_context: str,
    describer: VisionDescriber,
    dpi: int,
    cache_dir: Path | None,
    cancel_event: threading.Event | None,
    vlm_limiter: threading.Semaphore | None,
) -> _PageEnrichmentResult:
    _raise_if_cancelled(cancel_event)
    cached = _read_visual_page_cache(
        cache_dir,
        artifact_dir=artifact_dir,
        page_number=page_number,
        markdown=markdown,
        page_context=page_context,
        render_dpi=dpi,
    )
    if cached is not None:
        if not cached:
            return _PageEnrichmentResult(
                index=index,
                page_number=page_number,
                markdown=markdown,
                artifacts=[],
                detail=f"page {page_number} cached skip",
            )
        return _PageEnrichmentResult(
            index=index,
            page_number=page_number,
            markdown=_append_visual_contexts(
                markdown,
                page_number=page_number,
                artifacts=cached,
            ),
            artifacts=cached,
            detail=f"page {page_number} cached {len(cached)} figure(s)",
        )

    candidates = detect_figure_candidates(
        pdf_path,
        page_number=page_number,
        page_markdown=markdown,
        raw_payload=raw_payload,
    )
    if not candidates:
        _write_visual_page_cache(
            cache_dir,
            page_number=page_number,
            markdown=markdown,
            page_context=page_context,
            render_dpi=dpi,
            artifacts=[],
        )
        return _PageEnrichmentResult(
            index=index,
            page_number=page_number,
            markdown=markdown,
            artifacts=[],
            detail=f"page {page_number} no figure candidates",
        )

    artifacts: list[VisualArtifact] = []
    raw_responses: list[dict[str, object]] = []
    for candidate in candidates:
        _raise_if_cancelled(cancel_event)
        image_bytes = render_pdf_clip_jpeg(
            pdf_path,
            page_number=page_number,
            rect=candidate.rect,
            dpi=dpi,
        )
        if not _crop_has_visual_signal(image_bytes):
            raw_responses.append(
                {"candidate_index": candidate.index, "raw_response": "local_noise_filter_skip"}
            )
            continue

        with _vlm_slot(vlm_limiter, cancel_event):
            _raise_if_cancelled(cancel_event)
            raw_description = describer.describe_page(
                image_bytes=image_bytes,
                page_number=page_number,
                page_markdown=_candidate_prompt_context(page_context, candidate),
            )
        raw_responses.append(
            {"candidate_index": candidate.index, "raw_response": raw_description}
        )
        _raise_if_cancelled(cancel_event)
        description = _clean_description(raw_description)
        if not description:
            continue

        filename = f"page-{page_number:04d}-figure-{candidate.index:02d}.jpg"
        relative_path = Path("figures") / "grid" / document_key / filename
        target_path = artifact_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(image_bytes)
        artifacts.append(
            VisualArtifact(
                page=page_number,
                description=description,
                image_path=str(relative_path),
                image_sha256=_sha256_bytes(image_bytes),
                filename=filename,
                content_type="image/jpeg",
                size_bytes=len(image_bytes),
                bbox=candidate.bbox,
            )
        )

    _write_visual_page_cache(
        cache_dir,
        page_number=page_number,
        markdown=markdown,
        page_context=page_context,
        render_dpi=dpi,
        artifacts=artifacts,
        raw_responses=raw_responses,
    )
    return _PageEnrichmentResult(
        index=index,
        page_number=page_number,
        markdown=_append_visual_contexts(
            markdown,
            page_number=page_number,
            artifacts=artifacts,
        ),
        artifacts=artifacts,
        detail=(
            f"page {page_number} saved {len(artifacts)}/{len(candidates)} figure(s)"
            if artifacts
            else f"page {page_number} skipped {len(candidates)} candidate(s)"
        ),
    )


@contextmanager
def _vlm_slot(
    limiter: threading.Semaphore | None,
    cancel_event: threading.Event | None,
):
    if limiter is None:
        yield
        return
    acquired = False
    try:
        while not acquired:
            _raise_if_cancelled(cancel_event)
            acquired = limiter.acquire(timeout=0.2)
        yield
    finally:
        if acquired:
            limiter.release()


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if _is_cancelled(cancel_event):
        raise KeyboardInterrupt("VLM visual enrichment interrupted.")


def _is_cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def detect_figure_candidates(
    pdf_path: Path,
    *,
    page_number: int,
    page_markdown: str,
    raw_payload: dict[str, Any] | None = None,
) -> list[FigureCandidate]:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMuPDF is required for multimodal figure detection.") from exc

    doc = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} is outside {pdf_path.name} page count {len(doc)}.")
        page = doc.load_page(page_number - 1)
        layout_entries = _layout_entries_for_page(raw_payload, page_number) if raw_payload else []
        candidates = _layout_figure_candidates(
            layout_entries,
            page_number=page_number,
            page_rect=page.rect,
        )
        if layout_entries and not candidates:
            return []
        if not candidates:
            candidates = _local_pdf_figure_candidates(
                page,
                page_number=page_number,
                page_markdown=page_markdown,
            )
        candidates = _attach_nearby_text_to_candidates(candidates, page)
        return _dedupe_and_limit_candidates(candidates)
    finally:
        doc.close()


def _layout_figure_candidates(
    entries: list[dict[str, Any]],
    *,
    page_number: int,
    page_rect: object,
) -> list[FigureCandidate]:
    candidates: list[FigureCandidate] = []
    for entry in entries:
        label = str(entry.get("label") or entry.get("type") or "").strip().lower()
        if label not in {"figure", "figures", "image", "chart", "diagram"}:
            continue
        if bool(entry.get("isLikelyNoise") or entry.get("is_likely_noise")):
            continue
        confidence = _optional_float(entry.get("confidence"))
        if confidence is not None and confidence < 0.45:
            continue
        rect = _rect_from_layout_bbox(entry.get("bbox"), page_rect)
        if rect is None or _reject_candidate_rect(rect, page_rect):
            continue
        candidates.append(
            FigureCandidate(
                page=page_number,
                index=len(candidates) + 1,
                rect=_rect_tuple(rect),
                bbox=_bbox_payload(
                    rect,
                    page_rect,
                    source="llamaparse_layout",
                    confidence=confidence,
                    image_name=_optional_string(entry.get("image") or entry.get("figure_name")),
                ),
                source="llamaparse_layout",
                confidence=confidence,
                image_name=_optional_string(entry.get("image") or entry.get("figure_name")),
            )
        )
    return candidates


def _layout_entries_for_page(raw_payload: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    partitions = raw_payload.get("partitions")
    if isinstance(partitions, list):
        for partition in partitions:
            if not isinstance(partition, dict):
                continue
            offset = int(partition.get("page_offset") or 0)
            local_page = page_number - offset
            if local_page > 0:
                entries.extend(_layout_entries_for_page(partition, local_page))
        return entries

    stack: list[Any] = [raw_payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            layout = value.get("layout")
            value_page = _payload_page_number(value)
            if isinstance(layout, list) and value_page == page_number:
                entries.extend(item for item in layout if isinstance(item, dict))
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return entries


def _local_pdf_figure_candidates(
    page: object,
    *,
    page_number: int,
    page_markdown: str,
) -> list[FigureCandidate]:
    page_rect = page.rect
    candidates: list[FigureCandidate] = []
    image_rects = _image_block_rects(page)
    drawing_rects = _drawing_rects(page)
    text_rects = _text_block_rects(page)

    for rect in image_rects:
        rect = _expand_rect(rect, page_rect, 6.0)
        if _reject_candidate_rect(rect, page_rect):
            continue
        candidates.append(
            _candidate_from_rect(
                rect,
                page_rect,
                page_number=page_number,
                index=len(candidates) + 1,
                source="pdf_image_block",
            )
        )

    for rect in _cluster_rects(drawing_rects, margin=LOCAL_DRAWING_CLUSTER_MARGIN_PT):
        rect = _expand_to_nearby_text(rect, text_rects, page_rect)
        rect = _expand_rect(rect, page_rect, 8.0)
        if _reject_candidate_rect(rect, page_rect):
            continue
        candidates.append(
            _candidate_from_rect(
                rect,
                page_rect,
                page_number=page_number,
                index=len(candidates) + 1,
                source="pdf_vector_drawing",
            )
        )

    if not candidates and _markdown_has_image_reference(page_markdown):
        content_rect = _page_content_rect(page, exclude_text_only=True)
        if content_rect is not None and not _reject_candidate_rect(content_rect, page_rect):
            candidates.append(
                _candidate_from_rect(
                    content_rect,
                    page_rect,
                    page_number=page_number,
                    index=1,
                    source="markdown_image_fallback",
                )
            )
    return candidates


def _image_block_rects(page: object) -> list[object]:
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        return []
    rects: list[object] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != 1:
            continue
        bbox = block.get("bbox")
        if bbox:
            rects.append(_make_rect(page.rect, bbox))
    return rects


def _drawing_rects(page: object) -> list[object]:
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    rects: list[object] = []
    for drawing in drawings:
        if not isinstance(drawing, dict):
            continue
        rect = drawing.get("rect")
        if rect is None or rect.is_empty:
            continue
        if rect.width < 3 or rect.height < 3:
            continue
        rects.append(rect)
    return rects


def _text_block_rects(page: object) -> list[tuple[object, str]]:
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return []
    rects: list[tuple[object, str]] = []
    for block in blocks:
        if not isinstance(block, tuple) or len(block) < 5:
            continue
        block_type = block[6] if len(block) > 6 else 0
        if block_type != 0:
            continue
        text = str(block[4] or "").strip()
        if not text:
            continue
        rects.append((_make_rect(page.rect, block[:4]), text))
    return rects


def _cluster_rects(rects: list[object], *, margin: float) -> list[object]:
    clusters: list[object] = []
    for rect in rects:
        if rect.is_empty:
            continue
        merged = False
        for index, cluster in enumerate(clusters):
            if _rects_are_near(cluster, rect, margin):
                clusters[index] = cluster | rect
                merged = True
                break
        if not merged:
            clusters.append(rect)

    changed = True
    while changed:
        changed = False
        merged_clusters: list[object] = []
        for rect in clusters:
            for index, existing in enumerate(merged_clusters):
                if _rects_are_near(existing, rect, margin):
                    merged_clusters[index] = existing | rect
                    changed = True
                    break
            else:
                merged_clusters.append(rect)
        clusters = merged_clusters
    return clusters


def _rects_are_near(first: object, second: object, margin: float) -> bool:
    expanded = _raw_expand_rect(first, margin)
    return bool(expanded.intersects(second))


def _expand_to_nearby_text(rect: object, text_rects: list[tuple[object, str]], page_rect: object) -> object:
    expanded = rect
    near_rect = _raw_expand_rect(rect, TEXT_LABEL_EXPANSION_MARGIN_PT)
    for text_rect, text in text_rects:
        if len(text) > 220:
            continue
        if near_rect.intersects(text_rect) or _caption_is_nearby(rect, text_rect, text):
            expanded = expanded | text_rect
    return expanded & page_rect


def _caption_is_nearby(rect: object, text_rect: object, text: str) -> bool:
    if not re.match(r"(?i)^(fig\.?|figure|diagram)\b", text.strip()):
        return False
    vertical_gap = text_rect.y0 - rect.y1
    horizontal_overlap = min(rect.x1, text_rect.x1) - max(rect.x0, text_rect.x0)
    return 0 <= vertical_gap <= 36 and horizontal_overlap > min(rect.width, text_rect.width) * 0.25


def _page_content_rect(page: object, *, exclude_text_only: bool) -> object | None:
    rects: list[object] = []
    rects.extend(_image_block_rects(page))
    rects.extend(_drawing_rects(page))
    if not exclude_text_only:
        rects.extend(rect for rect, _text in _text_block_rects(page))
    if not rects:
        return None
    result = rects[0]
    for rect in rects[1:]:
        result = result | rect
    return _expand_rect(result, page.rect, 6.0)


def _dedupe_and_limit_candidates(candidates: list[FigureCandidate]) -> list[FigureCandidate]:
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            0 if item.source == "llamaparse_layout" else 1,
            item.rect[1],
            item.rect[0],
        ),
    )
    deduped: list[FigureCandidate] = []
    for candidate in sorted_candidates:
        if any(_rect_iou(candidate.rect, existing.rect) > 0.72 for existing in deduped):
            continue
        deduped.append(
            FigureCandidate(
                page=candidate.page,
                index=len(deduped) + 1,
                rect=candidate.rect,
                bbox={**candidate.bbox, "candidate_index": len(deduped) + 1},
                source=candidate.source,
                confidence=candidate.confidence,
                image_name=candidate.image_name,
                nearby_text=candidate.nearby_text,
            )
        )
        if len(deduped) >= _max_figure_candidates_per_page():
            break
    return deduped


def _candidate_from_rect(
    rect: object,
    page_rect: object,
    *,
    page_number: int,
    index: int,
    source: str,
) -> FigureCandidate:
    return FigureCandidate(
        page=page_number,
        index=index,
        rect=_rect_tuple(rect),
        bbox=_bbox_payload(rect, page_rect, source=source),
        source=source,
    )


def _attach_nearby_text_to_candidates(
    candidates: list[FigureCandidate],
    page: object,
) -> list[FigureCandidate]:
    if not candidates:
        return []
    text_rects = _text_block_rects(page)
    if not text_rects:
        return candidates
    enriched: list[FigureCandidate] = []
    for candidate in candidates:
        rect = _make_rect(page.rect, candidate.rect)
        nearby_text = _nearby_text_for_rect(rect, text_rects, page.rect)
        enriched.append(
            FigureCandidate(
                page=candidate.page,
                index=candidate.index,
                rect=candidate.rect,
                bbox=candidate.bbox,
                source=candidate.source,
                confidence=candidate.confidence,
                image_name=candidate.image_name,
                nearby_text=nearby_text,
            )
        )
    return enriched


def _nearby_text_for_rect(
    rect: object,
    text_rects: list[tuple[object, str]],
    page_rect: object,
) -> str:
    search_rect = _expand_rect(rect, page_rect, NEARBY_TEXT_MARGIN_PT)
    candidates: list[tuple[float, float, str]] = []
    for text_rect, text in text_rects:
        clean_text = _normalize_context_text(text)
        if not clean_text:
            continue
        if search_rect.intersects(text_rect) or _caption_is_nearby(rect, text_rect, clean_text):
            distance = _rect_distance(rect, text_rect)
            candidates.append((text_rect.y0, distance, clean_text))
    candidates.sort(key=lambda item: (item[0], item[1]))
    parts: list[str] = []
    seen: set[str] = set()
    for _y, _distance, text in candidates:
        if text in seen:
            continue
        seen.add(text)
        parts.append(text)
        if len("\n".join(parts)) >= MAX_NEARBY_TEXT_CHARS:
            break
    return _clip_text("\n".join(parts), MAX_NEARBY_TEXT_CHARS)


def _rect_distance(first: object, second: object) -> float:
    if first.intersects(second):
        return 0.0
    dx = max(first.x0 - second.x1, second.x0 - first.x1, 0.0)
    dy = max(first.y0 - second.y1, second.y0 - first.y1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _reject_candidate_rect(rect: object, page_rect: object) -> bool:
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return True
    page_area = max(page_rect.width * page_rect.height, 1.0)
    area_ratio = (rect.width * rect.height) / page_area
    if area_ratio < MIN_CANDIDATE_AREA_RATIO or area_ratio > MAX_CANDIDATE_AREA_RATIO:
        return True
    width_ratio = rect.width / max(page_rect.width, 1.0)
    height_ratio = rect.height / max(page_rect.height, 1.0)
    if max(width_ratio / max(height_ratio, 0.001), height_ratio / max(width_ratio, 0.001)) > 14:
        return True
    if rect.y1 < page_rect.height * HEADER_FOOTER_MARGIN_RATIO and area_ratio < 0.08:
        return True
    if rect.y0 > page_rect.height * (1 - HEADER_FOOTER_MARGIN_RATIO) and area_ratio < 0.08:
        return True
    if width_ratio > 0.88 and height_ratio < 0.045:
        return True
    return False


def _crop_has_visual_signal(image_bytes: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            gray = image.convert("L")
            histogram = gray.histogram()
            total = max(gray.width * gray.height, 1)
    except Exception:
        return False
    dark_ratio = sum(histogram[:36]) / total
    non_white_ratio = sum(histogram[:246]) / total
    if dark_ratio > MAX_RENDERED_DARK_RATIO:
        return False
    return non_white_ratio >= MIN_RENDERED_NON_WHITE_RATIO


def _candidate_prompt_context(document_context: str, candidate: FigureCandidate) -> str:
    bbox = candidate.bbox
    parts = [
        f"Candidate source: {candidate.source}\n"
        f"Candidate bbox: x={bbox.get('x')}, y={bbox.get('y')}, "
        f"w={bbox.get('w')}, h={bbox.get('h')} as page fractions."
    ]
    if candidate.nearby_text:
        parts.append(f"Nearby PDF text and likely caption:\n{candidate.nearby_text}")
    parts.append(f"Parsed document context:\n{document_context}")
    return "\n\n".join(parts)


def _document_context_by_page(
    parsed_pages: list[tuple[int, str]],
    *,
    document_key: str,
) -> dict[int, str]:
    contexts: dict[int, str] = {}
    for index, (page_number, markdown) in enumerate(parsed_pages):
        parts = [
            f"Document key: {document_key}",
            f"Current page: {page_number}",
        ]
        if index > 0:
            previous_page, previous_markdown = parsed_pages[index - 1]
            parts.append(
                "Previous page tail "
                f"(page {previous_page}):\n"
                + _clip_text(
                    _normalize_context_text(previous_markdown),
                    MAX_NEIGHBOR_PAGE_CONTEXT_CHARS,
                    tail=True,
                )
            )
        parts.append(
            "Current page parsed markdown:\n"
            + _clip_text(
                _normalize_context_text(markdown),
                MAX_CURRENT_PAGE_CONTEXT_CHARS,
            )
        )
        if index + 1 < len(parsed_pages):
            next_page, next_markdown = parsed_pages[index + 1]
            parts.append(
                f"Next page head (page {next_page}):\n"
                + _clip_text(
                    _normalize_context_text(next_markdown),
                    MAX_NEIGHBOR_PAGE_CONTEXT_CHARS,
                )
            )
        contexts[page_number] = "\n\n".join(part for part in parts if part.strip())
    return contexts


def _normalize_context_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clip_text(text: str, max_chars: int, *, tail: bool = False) -> str:
    if len(text) <= max_chars:
        return text
    if tail:
        return "... " + text[-max_chars:].lstrip()
    return text[:max_chars].rstrip() + " ..."


def _figure_text_span(
    corpus_text: str | None,
    *,
    page: PageRecord | None,
    image_path: str,
) -> tuple[int | None, int | None]:
    if not corpus_text or page is None:
        return (
            (page.start_char if page else None),
            (page.end_char if page else None),
        )
    image_index = corpus_text.find(image_path, page.start_char, page.end_char)
    if image_index < 0:
        return page.start_char, page.end_char
    marker_index = corpus_text.rfind(VISUAL_DESCRIPTION_MARKER, page.start_char, image_index)
    if marker_index < 0:
        marker_index = image_index
    next_marker = corpus_text.find(VISUAL_DESCRIPTION_MARKER, image_index, page.end_char)
    next_page = corpus_text.find("\n\n[Page ", image_index, page.end_char)
    ends = [value for value in (next_marker, next_page, page.end_char) if value >= 0]
    return marker_index, min(ends) if ends else page.end_char


def _bbox_payload(
    rect: object,
    page_rect: object,
    *,
    source: str,
    confidence: float | None = None,
    image_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "unit": "page_fraction",
        "x": round(rect.x0 / max(page_rect.width, 1.0), 6),
        "y": round(rect.y0 / max(page_rect.height, 1.0), 6),
        "w": round(rect.width / max(page_rect.width, 1.0), 6),
        "h": round(rect.height / max(page_rect.height, 1.0), 6),
        "source": source,
    }
    if confidence is not None:
        payload["confidence"] = confidence
    if image_name:
        payload["image_name"] = image_name
    return payload


def _rect_from_layout_bbox(bbox: object, page_rect: object) -> object | None:
    if not isinstance(bbox, dict):
        return None
    x = _optional_float(bbox.get("x"))
    y = _optional_float(bbox.get("y"))
    w = _optional_float(bbox.get("w"))
    h = _optional_float(bbox.get("h"))
    if None not in (x, y, w, h):
        if max(abs(x), abs(y), abs(w), abs(h)) > 1.5:
            return _make_rect(page_rect, (x, y, x + w, y + h))
        return _make_rect(
            page_rect,
            (
                page_rect.x0 + x * page_rect.width,
                page_rect.y0 + y * page_rect.height,
                page_rect.x0 + (x + w) * page_rect.width,
                page_rect.y0 + (y + h) * page_rect.height,
            ),
        )
    x0 = _optional_float(bbox.get("x0"))
    y0 = _optional_float(bbox.get("y0"))
    x1 = _optional_float(bbox.get("x1"))
    y1 = _optional_float(bbox.get("y1"))
    if None in (x0, y0, x1, y1):
        return None
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1.5:
        return _make_rect(
            page_rect,
            (
                page_rect.x0 + x0 * page_rect.width,
                page_rect.y0 + y0 * page_rect.height,
                page_rect.x0 + x1 * page_rect.width,
                page_rect.y0 + y1 * page_rect.height,
            ),
        )
    return _make_rect(page_rect, (x0, y0, x1, y1))


def _make_rect(reference: object, values: object) -> object:
    rect_type = type(reference)
    return rect_type(values)


def _expand_rect(rect: object, page_rect: object, margin: float) -> object:
    return _raw_expand_rect(rect, margin) & page_rect


def _raw_expand_rect(rect: object, margin: float) -> object:
    rect_type = type(rect)
    return rect_type(rect.x0 - margin, rect.y0 - margin, rect.x1 + margin, rect.y1 + margin)


def _rect_tuple(rect: object) -> tuple[float, float, float, float]:
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _rect_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if intersection <= 0:
        return 0.0
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    return intersection / max(first_area + second_area - intersection, 1.0)


def _payload_page_number(value: dict[str, Any]) -> int | None:
    for key in ("page", "page_number", "pageNumber"):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            return int(raw)
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    for key in ("page_index", "pageIndex"):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and raw >= 0:
            return int(raw) + 1
        if isinstance(raw, str) and raw.isdigit():
            return int(raw) + 1
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _markdown_has_image_reference(markdown: str) -> bool:
    return bool(re.search(r"!\[[^\]]*\]\([^)]+\)", markdown))


def _max_figure_candidates_per_page() -> int:
    raw = os.getenv("GRID_VLM_MAX_FIGURE_CANDIDATES_PER_PAGE")
    if not raw:
        return DEFAULT_MAX_FIGURE_CANDIDATES_PER_PAGE
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_FIGURE_CANDIDATES_PER_PAGE


def visual_artifacts_to_figures(
    artifacts: list[VisualArtifact],
    *,
    document_key: str,
    pages: list[PageRecord],
    corpus_text: str | None = None,
) -> list[FigureRecord]:
    figures: list[FigureRecord] = []
    for index, artifact in enumerate(artifacts, start=1):
        page = next((item for item in pages if item.page == artifact.page), None)
        start_char, end_char = _figure_text_span(
            corpus_text,
            page=page,
            image_path=artifact.image_path,
        )
        figures.append(
            FigureRecord(
                figure_id=f"grid/{document_key}#figure{index:04d}",
                page=artifact.page,
                description=artifact.description,
                image_path=artifact.image_path,
                image_sha256=artifact.image_sha256,
                filename=artifact.filename,
                content_type=artifact.content_type,
                size_bytes=artifact.size_bytes,
                category=artifact.category,
                start_char=start_char,
                end_char=end_char,
                bbox=artifact.bbox,
            )
        )
    return figures


def render_pdf_page_jpeg(pdf_path: Path, *, page_number: int, dpi: int) -> bytes:
    return render_pdf_clip_jpeg(pdf_path, page_number=page_number, rect=None, dpi=dpi)


def render_pdf_clip_jpeg(
    pdf_path: Path,
    *,
    page_number: int,
    rect: tuple[float, float, float, float] | None,
    dpi: int,
) -> bytes:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMuPDF is required for multimodal figure cropping.") from exc
    doc = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} is outside {pdf_path.name} page count {len(doc)}.")
        page = doc.load_page(page_number - 1)
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        clip = fitz.Rect(rect) if rect is not None else None
        if clip is not None:
            clip &= page.rect
            if clip.is_empty:
                raise ValueError(f"Figure crop for page {page_number} is empty.")
        pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        png_bytes = pixmap.tobytes("png")
    finally:
        doc.close()

    with Image.open(io.BytesIO(png_bytes)) as image:
        image = image.convert("RGB")
        if image.width > MAX_RENDER_WIDTH:
            ratio = MAX_RENDER_WIDTH / image.width
            image = image.resize((MAX_RENDER_WIDTH, max(1, int(image.height * ratio))))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()


def _description_prompt(*, page_number: int, page_markdown: str) -> str:
    context_excerpt = page_markdown.strip()[:7000]
    return (
        "You are enriching a parsed Grid document for multimodal retrieval.\n"
        "The attached image is a cropped candidate visual from one PDF page, not the full page.\n"
        "The text below gives document context: the document key, current page markdown, "
        "neighboring page snippets, candidate bbox, and nearby PDF text that may include the "
        "caption or explanatory paragraphs around the crop.\n"
        "Return useful figure context only when the crop is a necessary figure: an engineering "
        "diagram, one-line or network schematic, chart, plot, map, flow/process diagram, "
        "coordination curve, equipment drawing, or other non-table visual that helps answer "
        "technical power-system questions.\n"
        "Reject ordinary tables because LlamaParse Agentic already parses tables. Also reject "
        "forms, headers, footers, logos, signatures, decorative images, dark/blank blocks, "
        "plain paragraphs, and crops where the meaningful content is mostly text.\n\n"
        "Return JSON only with this shape:\n"
        '{"material_figure": true|false, "figure_type": "...", "description": "..."}\n\n'
        "When material_figure is false, description must be empty and figure_type should name "
        "the rejected class such as table, header, footer, logo, blank, dark, form, or text.\n"
        "When material_figure is true, write 6-12 detailed sentences. Use the surrounding "
        "text to identify the document section, caption, and terminology, but describe only "
        "relationships supported by the cropped image or the supplied context. Include visible "
        "title or caption text, component names, bus/line/equipment labels, arrows and topology, "
        "axes and units, numeric ranges, callouts, legends, color/line encodings, dependencies, "
        "and what the figure contributes beyond the parsed text. Do not invent values that are "
        "not visible or supplied in context; state uncertainty when a label is unreadable.\n\n"
        f"Page number: {page_number}\n"
        f"Document and candidate context:\n{context_excerpt}"
    )


def _append_visual_contexts(
    markdown: str,
    *,
    page_number: int,
    artifacts: list[VisualArtifact],
) -> str:
    if not artifacts:
        return markdown
    blocks = [
        _visual_context_block(artifact, page_number=page_number, index=index)
        for index, artifact in enumerate(artifacts, start=1)
    ]
    image_matches = list(re.finditer(r"!\[[^\]]*\]\([^)]+\)", markdown))
    if not image_matches:
        return f"{markdown.rstrip()}\n\n" + "\n\n".join(blocks)

    output: list[str] = []
    cursor = 0
    for index, match in enumerate(image_matches[: len(blocks)]):
        output.append(markdown[cursor : match.end()])
        output.append("\n\n")
        output.append(blocks[index])
        cursor = match.end()
    output.append(markdown[cursor:])
    if len(blocks) > len(image_matches):
        output.append("\n\n")
        output.append("\n\n".join(blocks[len(image_matches) :]))
    return "".join(output).strip()


def _visual_context_block(artifact: VisualArtifact, *, page_number: int, index: int) -> str:
    return (
        f"{VISUAL_DESCRIPTION_MARKER} - page {page_number} figure {index}\n\n"
        f"{artifact.description}\n\n"
        f"![Page {page_number} figure {index}]({artifact.image_path})"
    )


def _clean_description(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    payload = _json_from_text(raw)
    if payload is not None:
        material = payload.get("material_figure")
        if material is None:
            material = payload.get("material_visual_content")
        figure_type = str(payload.get("figure_type") or payload.get("visual_type") or "").strip()
        description = str(payload.get("description") or "").strip()
        if (
            material is True
            and description
            and not _looks_like_rejected_visual_type(figure_type)
            and not _looks_like_simple_definition_table(description)
        ):
            return description
        return ""
    if raw.upper().startswith("NO_MATERIAL_VISUAL_CONTENT"):
        return ""
    return ""


def _read_visual_page_cache(
    cache_dir: Path | None,
    *,
    artifact_dir: Path,
    page_number: int,
    markdown: str,
    page_context: str,
    render_dpi: int,
) -> list[VisualArtifact] | None:
    if cache_dir is None:
        return None
    cache_path = _visual_page_cache_path(cache_dir, page_number)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("version") != VISUAL_CACHE_VERSION
        or payload.get("page") != page_number
        or payload.get("markdown_sha256") != _sha256_text(markdown)
        or payload.get("context_sha256") != _sha256_text(page_context)
        or payload.get("render_dpi") != render_dpi
        or payload.get("max_render_width") != MAX_RENDER_WIDTH
    ):
        return None

    artifact_payloads = payload.get("artifacts")
    if not isinstance(artifact_payloads, list):
        return None
    artifacts: list[VisualArtifact] = []
    for artifact_payload in artifact_payloads:
        if not isinstance(artifact_payload, dict):
            return None
        try:
            artifact = VisualArtifact(
                page=int(artifact_payload["page"]),
                description=str(artifact_payload["description"]),
                image_path=str(artifact_payload["image_path"]),
                image_sha256=str(artifact_payload["image_sha256"]),
                filename=str(artifact_payload["filename"]),
                content_type=str(artifact_payload["content_type"]),
                size_bytes=int(artifact_payload["size_bytes"]),
                category=str(artifact_payload.get("category") or "figure_crop"),
                bbox=dict(artifact_payload.get("bbox") or {}),
            )
        except (KeyError, TypeError, ValueError):
            return None
        image_path = artifact_dir / artifact.image_path
        if not image_path.exists():
            return None
        try:
            if _sha256_bytes(image_path.read_bytes()) != artifact.image_sha256:
                return None
        except OSError:
            return None
        artifacts.append(artifact)
    return artifacts


def _write_visual_page_cache(
    cache_dir: Path | None,
    *,
    page_number: int,
    markdown: str,
    page_context: str,
    render_dpi: int,
    artifacts: list[VisualArtifact],
    raw_responses: list[dict[str, object]] | None = None,
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VISUAL_CACHE_VERSION,
        "page": page_number,
        "markdown_sha256": _sha256_text(markdown),
        "context_sha256": _sha256_text(page_context),
        "render_dpi": render_dpi,
        "max_render_width": MAX_RENDER_WIDTH,
        "artifacts": [_visual_artifact_to_cache(artifact) for artifact in artifacts],
        "raw_responses": raw_responses or [],
    }
    cache_path = _visual_page_cache_path(cache_dir, page_number)
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(cache_path)


def _visual_artifact_to_cache(artifact: VisualArtifact) -> dict[str, object]:
    return {
        "page": artifact.page,
        "description": artifact.description,
        "image_path": artifact.image_path,
        "image_sha256": artifact.image_sha256,
        "filename": artifact.filename,
        "content_type": artifact.content_type,
        "size_bytes": artifact.size_bytes,
        "category": artifact.category,
        "bbox": artifact.bbox,
    }


def _visual_page_cache_path(cache_dir: Path, page_number: int) -> Path:
    return cache_dir / f"page-{page_number:04d}.visual.json"


def _looks_like_simple_definition_table(description: str) -> bool:
    lowered = description.lower()
    simple_table_markers = (
        "glossary table",
        "definition table",
        "defines",
        "term names",
        "terms on the left",
        "definitions on the right",
        "two columns",
    )
    material_visual_markers = (
        "diagram",
        "chart",
        "flow",
        "axis",
        "axes",
        "graph",
        "map",
        "schematic",
        "block diagram",
        "signal flow",
    )
    return any(marker in lowered for marker in simple_table_markers) and not any(
        marker in lowered for marker in material_visual_markers
    )


def _looks_like_rejected_visual_type(figure_type: str) -> bool:
    lowered = figure_type.lower()
    rejected_markers = (
        "table",
        "form",
        "header",
        "footer",
        "logo",
        "blank",
        "dark",
        "text",
        "paragraph",
        "signature",
        "decorative",
    )
    return any(marker in lowered for marker in rejected_markers)


def _json_from_text(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _response_text(response: object) -> str:
    if hasattr(response, "model_dump"):
        response = response.model_dump(mode="json")
    if not isinstance(response, dict):
        return ""
    content = response.get("content")
    if content is None:
        output = response.get("output")
        if not isinstance(output, dict):
            return ""
        message = output.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif hasattr(item, "text") and isinstance(item.text, str):
            parts.append(item.text)
    return "\n".join(parts).strip()


def _is_retryable_api_error(exc: Exception) -> bool:
    text = str(exc).lower()
    retry_markers = (
        "throttl",
        "too many requests",
        "rate",
        "timeout",
        "temporar",
        "overload",
        "serviceunavailable",
        "service unavailable",
        "connection",
        "read timed out",
        "500",
        "502",
        "503",
        "504",
    )
    return any(marker in text for marker in retry_markers)


def _anthropic_model_id(value: str | None) -> str:
    raw = (value or DEFAULT_VLM_MODEL).strip() or DEFAULT_VLM_MODEL
    if "anthropic." in raw:
        raw = raw.split("anthropic.", 1)[1]
    return re.sub(r"-v[0-9]+:[0-9]+$", "", raw)


def _anthropic_model_max_tokens(client: object, model: str) -> int:
    try:
        models = getattr(client, "models")
        model_info = models.retrieve(model)
        max_tokens = getattr(model_info, "max_tokens", None)
        if isinstance(max_tokens, int) and max_tokens > 0:
            return max_tokens
    except Exception:
        pass
    return DEFAULT_MAX_OUTPUT_TOKENS


def _resolve_positive_int(value: int | None, *, env_name: str, default: int) -> int:
    raw = str(value if value is not None else os.getenv(env_name, str(default))).strip()
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{env_name} must be a positive integer.")
    return parsed


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))
