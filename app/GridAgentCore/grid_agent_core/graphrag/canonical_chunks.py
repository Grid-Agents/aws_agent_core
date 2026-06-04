"""Shared, offset-stable corpus pre-chunker.

Every GraphRAG method ingests this same chunk set as its atomic text unit, so
retrieval results carry a `chunk_id` that maps back to an exact char offset.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from .rag_common import split_sentences


@dataclass(frozen=True)
class CanonicalChunk:
    chunk_id: str
    document_id: str
    start_char: int
    end_char: int
    text: str


def build_canonical_chunks(
    corpus_dict: dict[str, str],
    *,
    target_chars: int = 1200,
) -> list[CanonicalChunk]:
    """Greedily pack offset-preserving sentences into ~target_chars chunks."""
    chunks: list[CanonicalChunk] = []
    for doc_id in sorted(corpus_dict):
        text = corpus_dict[doc_id]
        sents = split_sentences(text)  # [(start, end, text)]
        if not sents:
            continue
        i = 0
        ordinal = 0
        while i < len(sents):
            j = i
            cur = 0
            while j < len(sents) and cur + (sents[j][1] - sents[j][0]) <= target_chars:
                cur += sents[j][1] - sents[j][0]
                j += 1
            if j == i:
                j = i + 1  # one mega-sentence past the cap
            start = sents[i][0]
            end = sents[j - 1][1]
            chunks.append(CanonicalChunk(
                chunk_id=f"{doc_id}#{ordinal:04d}",
                document_id=doc_id,
                start_char=start,
                end_char=end,
                text=text[start:end],
            ))
            ordinal += 1
            i = j
    return chunks


CHUNKER_SIGNATURE = "canonical_v1__sentence_pack"


def write_canonical_chunks(chunks: list[CanonicalChunk], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(c) for c in chunks]))


def load_canonical_chunks(path: Path) -> dict[str, CanonicalChunk]:
    raw = json.loads(Path(path).read_text())
    return {c["chunk_id"]: CanonicalChunk(**c) for c in raw}
