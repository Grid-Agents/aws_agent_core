from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageRecord:
    page: int
    start_char: int
    end_char: int
    text_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FigureRecord:
    figure_id: str
    page: int
    description: str
    image_path: str
    image_sha256: str
    filename: str
    content_type: str
    size_bytes: int
    category: str = ""
    start_char: int | None = None
    end_char: int | None = None
    bbox: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FigureRecord":
        bbox = payload.get("bbox")
        return cls(
            figure_id=str(payload["figure_id"]),
            page=int(payload.get("page") or 0),
            description=str(payload.get("description") or ""),
            image_path=str(payload.get("image_path") or ""),
            image_sha256=str(payload.get("image_sha256") or ""),
            filename=str(payload.get("filename") or ""),
            content_type=str(payload.get("content_type") or "application/octet-stream"),
            size_bytes=int(payload.get("size_bytes") or 0),
            category=str(payload.get("category") or ""),
            start_char=int(payload["start_char"]) if payload.get("start_char") is not None else None,
            end_char=int(payload["end_char"]) if payload.get("end_char") is not None else None,
            bbox=dict(bbox) if isinstance(bbox, dict) else {},
        )


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    title: str
    category: str
    filename: str
    source_path: str
    text_path: str
    source_sha256: str
    text_sha256: str
    pages: list[PageRecord] = field(default_factory=list)
    figures: list[FigureRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pages"] = [page.to_dict() for page in self.pages]
        payload["figures"] = [figure.to_dict() for figure in self.figures]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DocumentRecord":
        return cls(
            document_id=str(payload["document_id"]),
            title=str(payload.get("title") or payload["document_id"]),
            category=str(payload.get("category") or ""),
            filename=str(payload.get("filename") or ""),
            source_path=str(payload.get("source_path") or ""),
            text_path=str(payload.get("text_path") or ""),
            source_sha256=str(payload.get("source_sha256") or ""),
            text_sha256=str(payload.get("text_sha256") or ""),
            pages=[
                PageRecord(
                    page=int(page["page"]),
                    start_char=int(page["start_char"]),
                    end_char=int(page["end_char"]),
                    text_sha256=str(page.get("text_sha256") or ""),
                )
                for page in payload.get("pages", [])
            ],
            figures=[
                FigureRecord.from_dict(figure)
                for figure in payload.get("figures", [])
                if isinstance(figure, dict)
            ],
        )


@dataclass
class Evidence:
    id: str
    document_id: str
    title: str
    category: str
    source_path: str
    page: int | None
    section: str
    span_text: str
    score: float
    artifact_source: str
    start_char: int
    end_char: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceEvent:
    id: int
    kind: str
    title: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
