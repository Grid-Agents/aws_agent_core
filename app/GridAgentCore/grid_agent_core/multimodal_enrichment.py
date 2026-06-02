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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from .models import FigureRecord, PageRecord
from .progress import ProgressBar, log_event
from .settings import model_id


DEFAULT_RENDER_DPI = 150
MAX_RENDER_WIDTH = 1600
DEFAULT_VLM_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_MAX_OUTPUT_TOKENS = 64000
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 2.0
DEFAULT_VLM_CONCURRENCY = 4
VISUAL_DESCRIPTION_MARKER = "### Visual context"
VISUAL_CACHE_VERSION = 1


@dataclass(frozen=True)
class VisualArtifact:
    page: int
    description: str
    image_path: str
    image_sha256: str
    filename: str
    content_type: str
    size_bytes: int
    category: str = "page_render"


@dataclass(frozen=True)
class _PageEnrichmentResult:
    index: int
    page_number: int
    markdown: str
    artifact: VisualArtifact | None
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
        self.max_tokens = _anthropic_model_max_tokens(self.client, self.model)
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

    results: list[_PageEnrichmentResult | None] = [None] * len(parsed_pages)
    for index, (page_number, markdown) in enumerate(parsed_pages):
        if index >= pages_to_process:
            results[index] = _PageEnrichmentResult(
                index=index,
                page_number=page_number,
                markdown=markdown,
                artifact=None,
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
            _raise_if_cancelled(cancel_event)
            result = future.result()
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
        result.artifact
        for result in results
        if result is not None and result.artifact is not None
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
        render_dpi=dpi,
    )
    if cached is not None:
        cached_description, cached_artifact = cached
        if cached_artifact is None:
            return _PageEnrichmentResult(
                index=index,
                page_number=page_number,
                markdown=markdown,
                artifact=None,
                detail=f"page {page_number} cached skip",
            )
        return _PageEnrichmentResult(
            index=index,
            page_number=page_number,
            markdown=_append_visual_context(
                markdown,
                page_number=page_number,
                description=cached_description,
                image_path=cached_artifact.image_path,
            ),
            artifact=cached_artifact,
            detail=f"page {page_number} cached visual",
        )

    with _vlm_slot(vlm_limiter, cancel_event):
        image_bytes = render_pdf_page_jpeg(pdf_path, page_number=page_number, dpi=dpi)
        _raise_if_cancelled(cancel_event)
        raw_description = describer.describe_page(
            image_bytes=image_bytes,
            page_number=page_number,
            page_markdown=markdown,
        )
    _raise_if_cancelled(cancel_event)
    description = _clean_description(raw_description)
    if not description:
        _write_visual_page_cache(
            cache_dir,
            page_number=page_number,
            markdown=markdown,
            render_dpi=dpi,
            description="",
            raw_response=raw_description,
            artifact=None,
        )
        return _PageEnrichmentResult(
            index=index,
            page_number=page_number,
            markdown=markdown,
            artifact=None,
            detail=f"page {page_number} skipped",
        )

    filename = f"page-{page_number:04d}-visual.jpg"
    relative_path = Path("figures") / "grid" / document_key / filename
    target_path = artifact_dir / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(image_bytes)
    artifact = VisualArtifact(
        page=page_number,
        description=description,
        image_path=str(relative_path),
        image_sha256=_sha256_bytes(image_bytes),
        filename=filename,
        content_type="image/jpeg",
        size_bytes=len(image_bytes),
    )
    _write_visual_page_cache(
        cache_dir,
        page_number=page_number,
        markdown=markdown,
        render_dpi=dpi,
        description=description,
        raw_response=raw_description,
        artifact=artifact,
    )
    return _PageEnrichmentResult(
        index=index,
        page_number=page_number,
        markdown=_append_visual_context(
            markdown,
            page_number=page_number,
            description=description,
            image_path=str(relative_path),
        ),
        artifact=artifact,
        detail=f"page {page_number} saved visual",
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


def visual_artifacts_to_figures(
    artifacts: list[VisualArtifact],
    *,
    document_key: str,
    pages: list[PageRecord],
) -> list[FigureRecord]:
    figures: list[FigureRecord] = []
    for index, artifact in enumerate(artifacts, start=1):
        page = next((item for item in pages if item.page == artifact.page), None)
        figures.append(
            FigureRecord(
                figure_id=f"grid/{document_key}#visual{index:04d}",
                page=artifact.page,
                description=artifact.description,
                image_path=artifact.image_path,
                image_sha256=artifact.image_sha256,
                filename=artifact.filename,
                content_type=artifact.content_type,
                size_bytes=artifact.size_bytes,
                category=artifact.category,
                start_char=page.start_char if page else None,
                end_char=page.end_char if page else None,
                bbox={},
            )
        )
    return figures


def render_pdf_page_jpeg(pdf_path: Path, *, page_number: int, dpi: int) -> bytes:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMuPDF is required for multimodal page rendering.") from exc
    doc = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} is outside {pdf_path.name} page count {len(doc)}.")
        page = doc.load_page(page_number - 1)
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
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
    markdown_excerpt = page_markdown.strip()[:2500]
    return (
        "You are enriching a parsed Grid document page for multimodal retrieval.\n"
        "Inspect the attached page image and compare it with the parser markdown excerpt.\n"
        "Return useful visual context only when the page contains a material diagram, chart, "
        "flow, form layout, equation layout, or other non-text visual structure that a "
        "text-only parser may not preserve.\n"
        "Ignore decorative logos, page headers, page footers, blank dark blocks, and ordinary "
        "plain-text paragraphs. Also ignore simple glossary, definition, and two-column term "
        "tables unless the visual layout itself is needed to understand relationships that the "
        "markdown text does not already preserve.\n\n"
        "Return JSON only with this shape:\n"
        '{"material_visual_content": true|false, "description": "..."}\n\n'
        "When material_visual_content is false, description must be empty.\n"
        "When true, description must be 3-8 concise sentences naming the visual content, key "
        "labels/axes/relationships, and why it matters for retrieval. Do not invent values that "
        "are not visible.\n\n"
        f"Page number: {page_number}\n"
        f"Parser markdown excerpt:\n{markdown_excerpt}"
    )


def _append_visual_context(markdown: str, *, page_number: int, description: str, image_path: str) -> str:
    block = (
        f"{VISUAL_DESCRIPTION_MARKER} - page {page_number}\n\n"
        f"{description}\n\n"
        f"![Page {page_number} visual context]({image_path})"
    )
    return f"{markdown.rstrip()}\n\n{block}".strip()


def _clean_description(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    payload = _json_from_text(raw)
    if payload is not None:
        material = payload.get("material_visual_content")
        description = str(payload.get("description") or "").strip()
        if material is True and description and not _looks_like_simple_definition_table(description):
            return description
        return ""
    if raw.upper().startswith("NO_MATERIAL_VISUAL_CONTENT"):
        return ""
    fallback = raw[:2000]
    return "" if _looks_like_simple_definition_table(fallback) else fallback


def _read_visual_page_cache(
    cache_dir: Path | None,
    *,
    artifact_dir: Path,
    page_number: int,
    markdown: str,
    render_dpi: int,
) -> tuple[str, VisualArtifact | None] | None:
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
        or payload.get("render_dpi") != render_dpi
        or payload.get("max_render_width") != MAX_RENDER_WIDTH
    ):
        return None

    description = str(payload.get("description") or "").strip()
    artifact_payload = payload.get("artifact")
    if not description:
        return "", None
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
            category=str(artifact_payload.get("category") or "page_render"),
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
    return description, artifact


def _write_visual_page_cache(
    cache_dir: Path | None,
    *,
    page_number: int,
    markdown: str,
    render_dpi: int,
    description: str,
    raw_response: str,
    artifact: VisualArtifact | None,
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VISUAL_CACHE_VERSION,
        "page": page_number,
        "markdown_sha256": _sha256_text(markdown),
        "render_dpi": render_dpi,
        "max_render_width": MAX_RENDER_WIDTH,
        "description": description,
        "raw_response": raw_response,
        "artifact": _visual_artifact_to_cache(artifact) if artifact is not None else None,
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
