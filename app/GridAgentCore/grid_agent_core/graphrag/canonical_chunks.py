from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass(frozen=True)
class CanonicalChunk:
    chunk_id: str
    document_id: str
    start_char: int
    end_char: int
    text: str


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    if not text:
        return []
    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in SENTENCE_BOUNDARY.finditer(text):
        end = match.start()
        _append_trimmed(spans, text, start, end)
        start = match.end()
    _append_trimmed(spans, text, start, len(text))
    return spans


def _append_trimmed(spans: list[tuple[int, int, str]], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end, text[start:end]))


def build_canonical_chunks(
    corpus_dict: dict[str, str],
    *,
    target_chars: int = 1200,
) -> list[CanonicalChunk]:
    chunks: list[CanonicalChunk] = []
    for document_id in sorted(corpus_dict):
        text = corpus_dict[document_id]
        sentences = split_sentences(text)
        if not sentences:
            continue
        index = 0
        ordinal = 0
        while index < len(sentences):
            end_index = index
            current_chars = 0
            while (
                end_index < len(sentences)
                and current_chars + (sentences[end_index][1] - sentences[end_index][0]) <= target_chars
            ):
                current_chars += sentences[end_index][1] - sentences[end_index][0]
                end_index += 1
            if end_index == index:
                end_index = index + 1
            start_char = sentences[index][0]
            end_char = sentences[end_index - 1][1]
            chunks.append(
                CanonicalChunk(
                    chunk_id=f"{document_id}#{ordinal:04d}",
                    document_id=document_id,
                    start_char=start_char,
                    end_char=end_char,
                    text=text[start_char:end_char],
                )
            )
            ordinal += 1
            index = end_index
    return chunks


def write_canonical_chunks(chunks: list[CanonicalChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(chunk) for chunk in chunks]), encoding="utf-8")


def load_canonical_chunks(path: Path) -> dict[str, CanonicalChunk]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["chunk_id"]: CanonicalChunk(**item) for item in raw}
