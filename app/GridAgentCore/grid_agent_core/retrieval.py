from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .colivara import load_colivara_hits
from .corpus import document_text, load_manifest, page_for_offset
from .indexes import SearchHit, load_graphrag_hits, load_pageindex_hits, load_vector_hits, tokenize
from .models import DocumentRecord, Evidence, FigureRecord
from .settings import s3_bucket, s3_prefix

MAX_FIND_MATCHES = 12
FIND_CONTEXT_CHARS = 1400
MAX_GRAPHRAG_HITS = 8
MAX_FIGURES_PER_EVIDENCE = 3


class GridRetrievalRepository:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir.expanduser().resolve()
        self.records = load_manifest(self.artifact_dir)
        self.by_id: dict[str, DocumentRecord] = {
            record.document_id: record for record in self.records
        }
        self._texts: dict[str, str] = {}

    def text(self, document_id: str) -> str:
        if document_id not in self._texts:
            self._texts[document_id] = document_text(
                self.artifact_dir, self.by_id[document_id]
            )
        return self._texts[document_id]

    def search(self, method: str, query: str, *, top_k: int = 8) -> list[Evidence]:
        start = time.time()
        if method == "vector":
            hits = load_vector_hits(self.artifact_dir, query, top_k=top_k)
        elif method == "pageindex":
            hits = load_pageindex_hits(self.artifact_dir, query, top_k=top_k)
        elif method == "find":
            hits = self._find_hits(query, top_k=top_k)
        elif method == "graphrag":
            hits = load_graphrag_hits(self.artifact_dir, query, top_k=top_k)
        elif method == "colivara":
            hits = load_colivara_hits(self.artifact_dir, query, top_k=top_k)
        else:
            raise ValueError(f"Unsupported retrieval method: {method}")
        evidence = [self._evidence(index, hit) for index, hit in enumerate(hits, start=1)]
        for item in evidence:
            item.metadata["latency_ms"] = round((time.time() - start) * 1000)
        return evidence

    def inspect(self, evidence: Evidence) -> Evidence:
        return evidence

    def _evidence(self, index: int, hit: SearchHit) -> Evidence:
        record = self.by_id[hit.document_id]
        text = hit.text
        if not text:
            doc_text = self.text(hit.document_id)
            text = doc_text[hit.start_char : hit.end_char]
        page = page_for_offset(record, hit.start_char)
        figures = self._figures_for_hit(record, hit.start_char, hit.end_char, page)
        metadata = dict(hit.metadata)
        figure_payloads = [self._figure_payload(figure) for figure in figures]
        if figure_payloads:
            existing_figures = metadata.get("figures")
            if isinstance(existing_figures, list):
                metadata["figures"] = [*existing_figures, *figure_payloads]
            else:
                metadata["figures"] = figure_payloads
        return Evidence(
            id=f"E{index}",
            document_id=hit.document_id,
            title=record.title,
            category=record.category,
            source_path=record.source_path,
            page=page,
            section=hit.section,
            span_text=text,
            score=hit.score,
            artifact_source=hit.source,
            start_char=hit.start_char,
            end_char=hit.end_char,
            metadata=metadata,
        )

    def _figures_for_hit(
        self,
        record: DocumentRecord,
        start_char: int,
        end_char: int,
        page: int | None,
    ) -> list[FigureRecord]:
        overlapping = [
            figure
            for figure in record.figures
            if figure.start_char is not None
            and figure.end_char is not None
            and figure.start_char < end_char
            and start_char < figure.end_char
        ]
        if overlapping:
            return overlapping[:MAX_FIGURES_PER_EVIDENCE]
        if page is None:
            return []
        return [
            figure
            for figure in record.figures
            if figure.page == page
        ][:MAX_FIGURES_PER_EVIDENCE]

    def _figure_payload(self, figure: FigureRecord) -> dict[str, Any]:
        local_path = self.artifact_dir / figure.image_path
        payload = figure.to_dict()
        payload["local_path"] = str(local_path)
        s3_uri = _s3_uri_for_artifact(figure.image_path)
        if s3_uri:
            payload["s3_uri"] = s3_uri
        return payload

    def _find_hits(self, query: str, *, top_k: int) -> list[SearchHit]:
        terms = [query.strip()]
        tokens = tokenize(query)
        if len(tokens) > 1:
            terms.extend(tokens[:8])
        seen: set[tuple[str, int, int]] = set()
        hits: list[SearchHit] = []
        for term in terms:
            needle = term.casefold()
            if not needle:
                continue
            for record in self.records:
                text = self.text(record.document_id)
                lowered = text.casefold()
                offset = 0
                while len(hits) < max(top_k, MAX_FIND_MATCHES):
                    match_start = lowered.find(needle, offset)
                    if match_start < 0:
                        break
                    match_end = match_start + len(needle)
                    start_char = max(0, match_start - FIND_CONTEXT_CHARS)
                    end_char = min(len(text), match_end + FIND_CONTEXT_CHARS)
                    key = (record.document_id, start_char, end_char)
                    if key not in seen:
                        seen.add(key)
                        hits.append(
                            SearchHit(
                                document_id=record.document_id,
                                start_char=start_char,
                                end_char=end_char,
                                text=text[start_char:end_char],
                                score=1.0 if term == query.strip() else 0.65,
                                source="find",
                                section=f"literal match: {term}",
                            )
                        )
                    offset = match_start + max(1, len(needle))
                if len(hits) >= top_k:
                    return hits[:top_k]
        return hits[:top_k]

def _s3_uri_for_artifact(relative_path: str) -> str:
    bucket = s3_bucket()
    if not bucket:
        return ""
    prefix = s3_prefix()
    key = f"{prefix}/{relative_path}" if prefix else relative_path
    return f"s3://{bucket}/{key}"
