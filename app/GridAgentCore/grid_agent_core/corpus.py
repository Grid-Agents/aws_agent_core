from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from .models import DocumentRecord, FigureRecord, PageRecord
from .progress import ProgressBar, log_event
from .settings import DEFAULT_ARTIFACT_DIR, grid_docs_dir

if TYPE_CHECKING:
    from .llama_parse_agentic import LlamaParseResult

try:
    from pypdf import PdfReader as PdfReader
except ModuleNotFoundError:  # pragma: no cover - optional parse-time dependency
    PdfReader = None

_NON_ID = re.compile(r"[^a-z0-9]+")
PARSER_PYPDF = "pypdf"
PARSER_LLAMAPARSE_AGENTIC = "llamaparse_agentic"
PARSE_RESUME_CACHE_DIRNAME = "parse_resume_cache"
LEGACY_PARSE_CACHE_DIRNAME = "parse"
PARSER_ALIASES = {
    "pypdf": PARSER_PYPDF,
    "llamaparse_agentic": PARSER_LLAMAPARSE_AGENTIC,
    "llamaparse-agentic": PARSER_LLAMAPARSE_AGENTIC,
}
LLAMAPARSE_AGENTIC_ARTIFACTS_VERSION = 4
DEFAULT_DOCUMENT_CONCURRENCY = 4
DEFAULT_VLM_CONCURRENCY = 4
FULL_GRID_CODE_FILENAME = "00_The_Full_Grid_Code.pdf"
DEFAULT_SMOKE_PAGE_RANGE = (1, 8)
DEFAULT_SMOKE_ARTIFACT_DIR = DEFAULT_ARTIFACT_DIR.parent / ".grid_smoke_artifacts"


def parse_pdf_agentic(*args, **kwargs):
    from .llama_parse_agentic import parse_pdf_agentic as _parse_pdf_agentic

    return _parse_pdf_agentic(*args, **kwargs)


def enrich_page_markdown_with_visuals(*args, **kwargs):
    from .multimodal_enrichment import enrich_page_markdown_with_visuals as _enrich

    return _enrich(*args, **kwargs)


def visual_artifacts_to_figures(*args, **kwargs):
    from .multimodal_enrichment import visual_artifacts_to_figures as _to_figures

    return _to_figures(*args, **kwargs)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def stable_document_id(category: str, filename: str) -> str:
    stem = Path(filename).stem.lower()
    raw = f"{category}/{stem}"
    return _NON_ID.sub("-", raw.lower()).strip("-")


def iter_grid_pdfs(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*.pdf")):
        if path.name.startswith("."):
            continue
        yield path


def find_full_grid_code_pdf(source_dir: Path) -> Path:
    candidates = [
        path
        for path in iter_grid_pdfs(source_dir)
        if path.name == FULL_GRID_CODE_FILENAME
    ]
    if not candidates:
        candidates = [
            path
            for path in iter_grid_pdfs(source_dir)
            if "full-grid-code" in _NON_ID.sub("-", path.stem.lower()).strip("-")
        ]
    if not candidates:
        raise FileNotFoundError(
            f"Could not find {FULL_GRID_CODE_FILENAME} under {source_dir}."
        )
    return candidates[0]


def parse_page_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("Use a 1-based page range like '1-8' or '5'.")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start <= 0 or end < start:
        raise argparse.ArgumentTypeError("Page range must be a positive inclusive range.")
    return start, end


def _page_range_label(page_range: tuple[int, int] | None) -> str | None:
    if page_range is None:
        return None
    start, end = page_range
    return f"{start}-{end}"


def extract_pdf(path: Path) -> tuple[str, list[PageRecord]]:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for parser='pypdf'. Install the build extras.")

    reader = PdfReader(str(path))
    page_texts: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = page_text.replace("\x00", "").strip()
        page_texts.append((index, page_text))
    return page_blocks(page_texts)


def extract_pdf_with_llamaparse_agentic(
    path: Path,
    *,
    artifact_dir: Path,
    document_key: str,
    show_progress: bool = False,
    cache_dir: Path | None = None,
    visual_cache_dir: Path | None = None,
    target_page_range: tuple[int, int] | None = None,
    multimodal_enrich: bool = False,
    vlm_concurrency: int | None = None,
    cancel_event: threading.Event | None = None,
    vlm_limiter: threading.Semaphore | None = None,
) -> tuple[str, list[PageRecord], list[FigureRecord], dict[str, object]]:
    parsed = parse_pdf_agentic(
        path,
        show_progress=show_progress,
        cache_dir=cache_dir,
        target_page_range=target_page_range,
    )
    return _llamaparse_result_to_corpus(
        parsed,
        pdf_path=path,
        artifact_dir=artifact_dir,
        document_key=document_key,
        show_progress=show_progress,
        visual_cache_dir=visual_cache_dir,
        multimodal_enrich=multimodal_enrich,
        vlm_concurrency=vlm_concurrency,
        cancel_event=cancel_event,
        vlm_limiter=vlm_limiter,
    )


def _llamaparse_result_to_corpus(
    parsed: LlamaParseResult,
    *,
    pdf_path: Path,
    artifact_dir: Path,
    document_key: str,
    show_progress: bool = False,
    visual_cache_dir: Path | None = None,
    multimodal_enrich: bool = False,
    vlm_concurrency: int | None = None,
    cancel_event: threading.Event | None = None,
    vlm_limiter: threading.Semaphore | None = None,
) -> tuple[str, list[PageRecord], list[FigureRecord], dict[str, object]]:
    page_markdown = [(page.page, page.markdown) for page in parsed.pages]
    visual_artifacts = []
    if multimodal_enrich:
        page_markdown, visual_artifacts = enrich_page_markdown_with_visuals(
            pdf_path,
            parsed_pages=page_markdown,
            artifact_dir=artifact_dir,
            document_key=document_key,
            raw_payload=parsed.raw_payload,
            cache_dir=visual_cache_dir,
            show_progress=show_progress,
            vlm_concurrency=vlm_concurrency,
            cancel_event=cancel_event,
            vlm_limiter=vlm_limiter,
        )
    text, pages = page_blocks(page_markdown)
    figures = visual_artifacts_to_figures(
        visual_artifacts,
        document_key=document_key,
        pages=pages,
        corpus_text=text,
    )
    return text, pages, figures, parsed.raw_payload


def page_blocks(page_texts: list[tuple[int, str]]) -> tuple[str, list[PageRecord]]:
    page_records: list[PageRecord] = []
    parts: list[str] = []
    cursor = 0
    for page_number, page_text in page_texts:
        clean_text = page_text.replace("\x00", "").strip()
        prefix = "\n\n" if parts else ""
        block = f"{prefix}[Page {page_number}]\n{clean_text}\n"
        start = cursor + len(prefix)
        parts.append(block)
        cursor += len(block)
        page_records.append(
            PageRecord(
                page=page_number,
                start_char=start,
                end_char=cursor,
                text_sha256=sha256_text(clean_text),
            )
        )
    return "".join(parts), page_records


def _write_source_document_metadata(source_dir: Path, artifact_dir: Path, pdf_paths: list[Path]) -> None:
    documents: list[dict[str, object]] = []
    total_pages = 0
    total_bytes = 0
    for pdf_path in pdf_paths:
        source_bytes = pdf_path.read_bytes()
        size_bytes = len(source_bytes)
        page_count = _pdf_page_count(pdf_path)
        if page_count is not None:
            total_pages += page_count
        total_bytes += size_bytes
        documents.append(
            {
                "category": pdf_path.parent.name,
                "filename": pdf_path.name,
                "relative_path": str(pdf_path.relative_to(source_dir)),
                "page_count": page_count,
                "size_bytes": size_bytes,
                "source_sha256": sha256_bytes(source_bytes),
            }
        )

    payload = {
        "source_dir": str(source_dir),
        "document_count": len(documents),
        "known_page_count": total_pages,
        "total_size_bytes": total_bytes,
        "documents": documents,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = artifact_dir / "source_document_metadata.json"
    metadata_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(
        "Source document analysis: "
        f"{len(documents)} PDFs, {total_pages} known pages, {_format_bytes(total_bytes)} total. "
        f"Metadata: {metadata_path}"
    )
    for item in documents:
        page_label = item["page_count"] if item["page_count"] is not None else "unknown"
        print(f"  - {item['relative_path']}: {page_label} pages, {_format_bytes(int(item['size_bytes']))}")


def _pdf_page_count(path: Path) -> int | None:
    if PdfReader is None:
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def _format_bytes(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size_bytes} B"


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise KeyboardInterrupt("Grid document parsing interrupted.")


def normalize_parser(parser: str) -> str:
    try:
        return PARSER_ALIASES[parser.strip().casefold()]
    except KeyError as exc:
        raise ValueError(
            "Unsupported parser. Use 'pypdf' or 'llamaparse-agentic'."
        ) from exc


def _resolve_positive_int(value: int | None, *, env_name: str, default: int) -> int:
    raw = str(value if value is not None else os.getenv(env_name, str(default))).strip()
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{env_name} must be a positive integer.")
    return parsed


def build_corpus(
    source_dir: Path,
    artifact_dir: Path,
    *,
    force: bool = False,
    parser: str = PARSER_PYPDF,
    resume: bool = True,
    show_progress: bool = False,
    pdf_paths: list[Path] | None = None,
    llamaparse_page_range: tuple[int, int] | None = None,
    multimodal_enrich: bool | None = None,
    document_concurrency: int | None = None,
    vlm_concurrency: int | None = None,
) -> list[DocumentRecord]:
    source_dir = source_dir.expanduser().resolve()
    artifact_dir = artifact_dir.expanduser().resolve()
    parser_id = normalize_parser(parser)
    from .multimodal_enrichment import multimodal_enrichment_enabled

    multimodal_enrich = multimodal_enrichment_enabled(multimodal_enrich)
    if llamaparse_page_range is not None and parser_id != PARSER_LLAMAPARSE_AGENTIC:
        raise ValueError("llamaparse_page_range requires parser='llamaparse-agentic'.")
    if multimodal_enrich and parser_id != PARSER_LLAMAPARSE_AGENTIC:
        raise ValueError("multimodal_enrich requires parser='llamaparse-agentic'.")
    doc_workers = _resolve_positive_int(
        document_concurrency,
        env_name="GRID_PARSE_DOCUMENT_CONCURRENCY",
        default=DEFAULT_DOCUMENT_CONCURRENCY,
    )
    vlm_workers = _resolve_positive_int(
        vlm_concurrency,
        env_name="GRID_VLM_CONCURRENCY",
        default=DEFAULT_VLM_CONCURRENCY,
    )
    corpus_dir = artifact_dir / "corpus" / "grid"
    raw_dir = artifact_dir / "raw"
    parse_dir = _parse_resume_cache_dir(artifact_dir, parser_id)
    manifest_path = artifact_dir / "manifest.jsonl"
    scoped_build = pdf_paths is not None or llamaparse_page_range is not None
    if manifest_path.exists() and not force and not scoped_build:
        return load_manifest(artifact_dir)

    corpus_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    parse_dir.mkdir(parents=True, exist_ok=True)
    prior_records = _load_prior_records(artifact_dir) if resume else {}
    selected_pdf_paths = (
        [path.expanduser().resolve() for path in pdf_paths]
        if pdf_paths is not None
        else list(iter_grid_pdfs(source_dir))
    )
    if not selected_pdf_paths:
        raise FileNotFoundError(f"No PDF files found under {source_dir}")
    _write_source_document_metadata(source_dir, artifact_dir, selected_pdf_paths)
    doc_workers = min(doc_workers, len(selected_pdf_paths))
    if show_progress:
        log_event(
            f"documents={len(selected_pdf_paths)} concurrency={doc_workers} "
            f"parser={parser_id} multimodal_enrich={multimodal_enrich} "
            f"anthropic_vlm_slots={vlm_workers if multimodal_enrich else 0}",
            label="parse",
        )

    progress = ProgressBar("Parsing Grid PDFs", len(selected_pdf_paths), enabled=show_progress)
    records_by_index: list[DocumentRecord | None] = [None] * len(selected_pdf_paths)
    cancel_event = threading.Event()
    vlm_limiter = threading.BoundedSemaphore(vlm_workers) if multimodal_enrich else None
    executor = ThreadPoolExecutor(max_workers=doc_workers)
    futures = {
        executor.submit(
            _build_document_record,
            pdf_path,
            artifact_dir,
            parse_dir,
            parser_id=parser_id,
            resume=resume,
            prior_record=prior_records.get(_document_cache_key(pdf_path)),
            show_progress=show_progress,
            llamaparse_page_range=llamaparse_page_range,
            multimodal_enrich=multimodal_enrich,
            vlm_concurrency=vlm_workers,
            cancel_event=cancel_event,
            vlm_limiter=vlm_limiter,
        ): index
        for index, pdf_path in enumerate(selected_pdf_paths)
    }
    try:
        for future in as_completed(futures):
            index = futures[future]
            record = future.result()
            _raise_if_cancelled(cancel_event)
            records_by_index[index] = record
            progress.advance(detail=f"{Path(record.source_path).name}")
        missing = [
            selected_pdf_paths[index].name
            for index, record in enumerate(records_by_index)
            if record is None
        ]
        if missing:
            raise RuntimeError(
                "Grid document parsing did not produce records for: " + ", ".join(missing)
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

    records = [record for record in records_by_index if record is not None]
    write_manifest(artifact_dir, records)
    (artifact_dir / "parse_metadata.json").write_text(
        json.dumps(
            {
                "parser": parser_id,
                "document_count": len(records),
                "resume": resume,
                "llamaparse_page_range": _page_range_label(llamaparse_page_range),
                "multimodal_enrich": multimodal_enrich,
                "document_concurrency": doc_workers,
                "vlm_concurrency": vlm_workers,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return records


def _build_document_record(
    pdf_path: Path,
    artifact_dir: Path,
    parse_dir: Path,
    *,
    parser_id: str,
    resume: bool,
    prior_record: DocumentRecord | None,
    show_progress: bool,
    llamaparse_page_range: tuple[int, int] | None,
    multimodal_enrich: bool,
    vlm_concurrency: int,
    cancel_event: threading.Event | None,
    vlm_limiter: threading.Semaphore | None,
) -> DocumentRecord:
    _raise_if_cancelled(cancel_event)
    category = pdf_path.parent.name
    document_id = stable_document_id(category, pdf_path.name)
    source_bytes = pdf_path.read_bytes()
    source_sha = sha256_bytes(source_bytes)
    cached = (
        _cached_document_record(
            artifact_dir,
            parse_dir,
            document_id,
            source_sha256=source_sha,
            parser_id=parser_id,
            prior_record=prior_record,
            llamaparse_page_range=llamaparse_page_range,
            multimodal_enrich=multimodal_enrich,
        )
        if resume
        else None
    )
    if cached is not None:
        return cached
    legacy = (
        _legacy_cached_document_record(
            pdf_path,
            artifact_dir,
            parse_dir,
            document_id,
            source_sha256=source_sha,
            parser_id=parser_id,
            llamaparse_page_range=llamaparse_page_range,
        )
        if resume
        else None
    )
    if legacy is not None:
        _write_document_sidecar(
            parse_dir,
            document_id,
            parser_id=parser_id,
            record=legacy,
            llamaparse_page_range=llamaparse_page_range,
            multimodal_enrich=multimodal_enrich,
        )
        return legacy

    _raise_if_cancelled(cancel_event)
    if parser_id == PARSER_LLAMAPARSE_AGENTIC:
        partition_cache_dir = _partition_cache_dir(parse_dir, document_id) if resume else None
        visual_cache_dir = _visual_cache_dir(parse_dir, document_id) if resume else None
        text, pages, figures, raw_payload = extract_pdf_with_llamaparse_agentic(
            pdf_path,
            artifact_dir=artifact_dir,
            document_key=document_id,
            show_progress=show_progress,
            cache_dir=partition_cache_dir,
            visual_cache_dir=visual_cache_dir,
            target_page_range=llamaparse_page_range,
            multimodal_enrich=multimodal_enrich,
            vlm_concurrency=vlm_concurrency,
            cancel_event=cancel_event,
            vlm_limiter=vlm_limiter,
        )
        raw_parse_path = parse_dir / f"{document_id}.raw.json"
        raw_parse_path.write_text(
            json.dumps(raw_payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
    else:
        text, pages = extract_pdf(pdf_path)
        figures = []
    relative_text = Path("corpus") / "grid" / f"{document_id}.txt"
    text_path = artifact_dir / relative_text
    text_path.write_text(text, encoding="utf-8")

    relative_raw = Path("raw") / category / pdf_path.name
    raw_path = artifact_dir / relative_raw
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(source_bytes)

    record = DocumentRecord(
        document_id=f"grid/{document_id}.txt",
        title=pdf_path.stem,
        category=category,
        filename=pdf_path.name,
        source_path=str(relative_raw),
        text_path=str(relative_text),
        source_sha256=source_sha,
        text_sha256=sha256_text(text),
        pages=pages,
        figures=figures,
    )
    _write_document_sidecar(
        parse_dir,
        document_id,
        parser_id=parser_id,
        record=record,
        llamaparse_page_range=llamaparse_page_range,
        multimodal_enrich=multimodal_enrich,
    )
    return record


def _parse_resume_cache_dir(artifact_dir: Path, parser_id: str) -> Path:
    parse_dir = artifact_dir / PARSE_RESUME_CACHE_DIRNAME / parser_id / "grid"
    legacy_dir = artifact_dir / LEGACY_PARSE_CACHE_DIRNAME / parser_id / "grid"
    if legacy_dir.exists() and not parse_dir.exists():
        parse_dir.parent.mkdir(parents=True, exist_ok=True)
        legacy_dir.rename(parse_dir)
    return parse_dir


def _partition_cache_dir(parse_dir: Path, document_id: str) -> Path:
    cache_dir = parse_dir / f"{document_id}.partition_cache"
    legacy_dir = parse_dir / f"{document_id}.parts"
    if legacy_dir.exists() and not cache_dir.exists():
        legacy_dir.rename(cache_dir)
    return cache_dir


def _visual_cache_dir(parse_dir: Path, document_id: str) -> Path:
    return parse_dir / f"{document_id}.visual_cache"


def _document_cache_key(pdf_path: Path) -> str:
    return stable_document_id(pdf_path.parent.name, pdf_path.name)


def _load_prior_records(artifact_dir: Path) -> dict[str, DocumentRecord]:
    try:
        records = load_manifest(artifact_dir)
    except FileNotFoundError:
        return {}
    result: dict[str, DocumentRecord] = {}
    for record in records:
        result[Path(record.text_path).stem] = record
    return result


def _write_document_sidecar(
    parse_dir: Path,
    document_id: str,
    *,
    parser_id: str,
    record: DocumentRecord,
    llamaparse_page_range: tuple[int, int] | None = None,
    multimodal_enrich: bool = False,
) -> None:
    sidecar_path = parse_dir / f"{document_id}.record.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "parser": parser_id,
                "source_sha256": record.source_sha256,
                "llamaparse_agentic_artifacts_version": (
                    LLAMAPARSE_AGENTIC_ARTIFACTS_VERSION
                    if parser_id == PARSER_LLAMAPARSE_AGENTIC
                    else 0
                ),
                "llamaparse_page_range": _page_range_label(llamaparse_page_range),
                "multimodal_enrich": multimodal_enrich,
                "record": record.to_dict(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _cached_document_record(
    artifact_dir: Path,
    parse_dir: Path,
    document_id: str,
    *,
    source_sha256: str,
    parser_id: str,
    prior_record: DocumentRecord | None,
    llamaparse_page_range: tuple[int, int] | None,
    multimodal_enrich: bool,
) -> DocumentRecord | None:
    sidecar_path = parse_dir / f"{document_id}.record.json"
    candidates: list[DocumentRecord] = []
    if sidecar_path.exists():
        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if (
                payload.get("parser") == parser_id
                and payload.get("source_sha256") == source_sha256
                and payload.get("llamaparse_page_range") == _page_range_label(llamaparse_page_range)
                and bool(payload.get("multimodal_enrich")) == multimodal_enrich
                and _sidecar_has_required_artifacts(payload, parser_id)
            ):
                candidates.append(DocumentRecord.from_dict(payload["record"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if prior_record is not None and parser_id != PARSER_LLAMAPARSE_AGENTIC:
        candidates.append(prior_record)

    for record in candidates:
        if _record_artifacts_are_current(
            artifact_dir,
            parse_dir,
            document_id,
            record,
            source_sha256=source_sha256,
            parser_id=parser_id,
            multimodal_enrich=multimodal_enrich,
        ):
            return record
    return None


def _sidecar_has_required_artifacts(payload: dict[str, object], parser_id: str) -> bool:
    if parser_id != PARSER_LLAMAPARSE_AGENTIC:
        return True
    return (
        payload.get("llamaparse_agentic_artifacts_version")
        == LLAMAPARSE_AGENTIC_ARTIFACTS_VERSION
    )


def _record_artifacts_are_current(
    artifact_dir: Path,
    parse_dir: Path,
    document_id: str,
    record: DocumentRecord,
    *,
    source_sha256: str,
    parser_id: str,
    multimodal_enrich: bool,
) -> bool:
    if record.source_sha256 != source_sha256:
        return False
    text_path = artifact_dir / record.text_path
    raw_path = artifact_dir / record.source_path
    if not text_path.exists() or not raw_path.exists():
        return False
    if parser_id == PARSER_LLAMAPARSE_AGENTIC:
        from .llama_parse_agentic import payload_matches_parsebench_agentic

        raw_parse_path = parse_dir / f"{document_id}.raw.json"
        if not raw_parse_path.exists():
            return False
        try:
            raw_payload = json.loads(raw_parse_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not payload_matches_parsebench_agentic(raw_payload):
            return False
        if record.figures and not multimodal_enrich:
            return False
        for figure in record.figures:
            image_path = artifact_dir / figure.image_path
            if not image_path.exists() or sha256_bytes(image_path.read_bytes()) != figure.image_sha256:
                return False
    text = text_path.read_text(encoding="utf-8", errors="replace")
    return sha256_text(text) == record.text_sha256


def _legacy_cached_document_record(
    pdf_path: Path,
    artifact_dir: Path,
    parse_dir: Path,
    document_id: str,
    *,
    source_sha256: str,
    parser_id: str,
    llamaparse_page_range: tuple[int, int] | None,
) -> DocumentRecord | None:
    if parser_id == PARSER_LLAMAPARSE_AGENTIC or llamaparse_page_range is not None:
        return None
    category = pdf_path.parent.name
    relative_text = Path("corpus") / "grid" / f"{document_id}.txt"
    relative_raw = Path("raw") / category / pdf_path.name
    text_path = artifact_dir / relative_text
    raw_path = artifact_dir / relative_raw
    if not text_path.exists() or not raw_path.exists():
        return None
    if sha256_bytes(raw_path.read_bytes()) != source_sha256:
        return None
    if parser_id == PARSER_LLAMAPARSE_AGENTIC and not (parse_dir / f"{document_id}.raw.json").exists():
        return None
    text = text_path.read_text(encoding="utf-8", errors="replace")
    pages = _page_records_from_corpus_text(text)
    if not pages:
        return None
    return DocumentRecord(
        document_id=f"grid/{document_id}.txt",
        title=pdf_path.stem,
        category=category,
        filename=pdf_path.name,
        source_path=str(relative_raw),
        text_path=str(relative_text),
        source_sha256=source_sha256,
        text_sha256=sha256_text(text),
        pages=pages,
    )


def _page_records_from_corpus_text(text: str) -> list[PageRecord]:
    matches = list(re.finditer(r"(?m)^\[Page ([0-9]+)\]$", text))
    pages: list[PageRecord] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end].strip()
        pages.append(
            PageRecord(
                page=int(match.group(1)),
                start_char=match.start(),
                end_char=end,
                text_sha256=sha256_text(block),
            )
        )
    return pages


def write_manifest(artifact_dir: Path, records: list[DocumentRecord]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")
    revision = hashlib.sha256(
        "\n".join(_record_revision_line(record) for record in records).encode("utf-8")
    ).hexdigest()
    (artifact_dir / "artifact_revision.txt").write_text(revision + "\n", encoding="utf-8")


def _record_revision_line(record: DocumentRecord) -> str:
    figure_hashes = ",".join(
        f"{figure.figure_id}:{figure.image_sha256}" for figure in record.figures
    )
    return f"{record.document_id}:{record.text_sha256}:{figure_hashes}"


def load_manifest(artifact_dir: Path) -> list[DocumentRecord]:
    manifest_path = artifact_dir / "manifest.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing Grid manifest: {manifest_path}")
    records: list[DocumentRecord] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(DocumentRecord.from_dict(json.loads(line)))
    return records


def document_text(artifact_dir: Path, record: DocumentRecord) -> str:
    return (artifact_dir / record.text_path).read_text(encoding="utf-8", errors="replace")


def page_for_offset(record: DocumentRecord, start_char: int) -> int | None:
    for page in record.pages:
        if page.start_char <= start_char < page.end_char:
            return page.page
    return record.pages[-1].page if record.pages else None


def _print_smoke_summary(
    artifact_dir: Path,
    records: list[DocumentRecord],
    *,
    page_range: tuple[int, int],
    duration_seconds: float,
) -> None:
    if not records:
        return
    record = records[0]
    text_path = artifact_dir / record.text_path
    text = text_path.read_text(encoding="utf-8", errors="replace")
    pages = ", ".join(str(page.page) for page in record.pages) or "none"
    markdown_image_refs = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", text))
    figure_bytes = sum(figure.size_bytes for figure in record.figures)

    print("\nFull Grid Code smoke summary")
    print(f"  Page range requested: {_page_range_label(page_range)}")
    print(f"  Parsed pages returned: {pages}")
    print(f"  Duration: {duration_seconds:.1f}s")
    print(f"  Parsed text: {text_path} ({len(text)} chars)")
    print(f"  Markdown image refs: {markdown_image_refs}")
    print(f"  Linked images saved: {len(record.figures)} ({_format_bytes(figure_bytes)})")
    for figure in record.figures[:12]:
        print(
            "  - "
            f"page={figure.page} category={figure.category} "
            f"size={_format_bytes(figure.size_bytes)} path={figure.image_path}"
        )
    if len(record.figures) > 12:
        print(f"  ... {len(record.figures) - 12} more linked image(s)")

    preview = text.strip()[:1200]
    if preview:
        print("\nParsed text preview")
        print(preview)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Grid PDFs into a text corpus and manifest.")
    parser.add_argument("--source-dir", type=Path, default=grid_docs_dir())
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help=(
            f"Artifact output directory. Defaults to {DEFAULT_ARTIFACT_DIR}; "
            f"smoke mode defaults to {DEFAULT_SMOKE_ARTIFACT_DIR}."
        ),
    )
    parser.add_argument(
        "--parser",
        default=None,
        choices=sorted(PARSER_ALIASES),
    )
    parser.add_argument(
        "--smoke-full-grid-code",
        action="store_true",
        help=(
            f"Parse only {FULL_GRID_CODE_FILENAME} with LlamaParse Agentic and "
            "write a small smoke-test artifact set."
        ),
    )
    parser.add_argument(
        "--smoke-page-range",
        type=parse_page_range,
        default=_page_range_label(DEFAULT_SMOKE_PAGE_RANGE),
        help="1-based inclusive page range for --smoke-full-grid-code. Defaults to 1-8.",
    )
    parser.add_argument(
        "--multimodal-enrich",
        action="store_true",
        default=None,
        help=(
            "Detect candidate figures, ask an Anthropic VLM for figure-only descriptions, "
            "insert them into Markdown, and save linked cropped figure images."
        ),
    )
    parser.add_argument(
        "--no-multimodal-enrich",
        action="store_false",
        dest="multimodal_enrich",
        help="Disable VLM visual enrichment even if GRID_MULTIMODAL_ENRICH is set.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-resume", action="store_true", help="Reparse PDFs even when matching artifacts exist.")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars.")
    parser.add_argument(
        "--document-concurrency",
        type=int,
        default=None,
        help=(
            "Number of Grid PDFs to parse in parallel. Defaults to "
            "GRID_PARSE_DOCUMENT_CONCURRENCY or 4."
        ),
    )
    parser.add_argument(
        "--vlm-concurrency",
        type=int,
        default=None,
        help=(
            "Run-wide number of Anthropic VLM figure-crop calls to run in parallel. "
            "Defaults to GRID_VLM_CONCURRENCY or 4."
        ),
    )
    args = parser.parse_args()

    parser_name = args.parser
    if parser_name is None:
        parser_name = (
            "llamaparse-agentic"
            if args.smoke_full_grid_code
            else os.getenv("GRID_PARSE_PROVIDER", PARSER_PYPDF)
        )
    parser_id = normalize_parser(parser_name)
    if args.smoke_full_grid_code and parser_id != PARSER_LLAMAPARSE_AGENTIC:
        raise SystemExit("--smoke-full-grid-code requires --parser llamaparse-agentic.")

    artifact_dir = args.artifact_dir or (
        DEFAULT_SMOKE_ARTIFACT_DIR if args.smoke_full_grid_code else DEFAULT_ARTIFACT_DIR
    )
    pdf_paths = None
    llamaparse_page_range = None
    if args.smoke_full_grid_code:
        from .multimodal_enrichment import multimodal_enrichment_enabled

        full_grid_code_pdf = find_full_grid_code_pdf(args.source_dir)
        pdf_paths = [full_grid_code_pdf]
        llamaparse_page_range = args.smoke_page_range
        print(
            "Running Full Grid Code smoke parse: "
            f"{full_grid_code_pdf} pages {_page_range_label(llamaparse_page_range)} "
            f"-> {artifact_dir}; multimodal_enrich={multimodal_enrichment_enabled(args.multimodal_enrich)}"
        )

    start_time = time.time()
    try:
        records = build_corpus(
            args.source_dir,
            artifact_dir,
            force=args.force,
            parser=parser_name,
            resume=not args.no_resume,
            show_progress=not args.no_progress,
            pdf_paths=pdf_paths,
            llamaparse_page_range=llamaparse_page_range,
            multimodal_enrich=args.multimodal_enrich,
            document_concurrency=args.document_concurrency,
            vlm_concurrency=args.vlm_concurrency,
        )
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Cancelled queued parse/VLM work and exiting now "
            "to stop in-flight worker threads.",
            file=sys.stderr,
            flush=True,
        )
        sys.stdout.flush()
        os._exit(130)
    duration = time.time() - start_time
    print(f"Parsed {len(records)} Grid documents with {parser_id} into {artifact_dir}")
    if args.smoke_full_grid_code and llamaparse_page_range is not None:
        _print_smoke_summary(
            artifact_dir,
            records,
            page_range=llamaparse_page_range,
            duration_seconds=duration,
        )


if __name__ == "__main__":
    main()
