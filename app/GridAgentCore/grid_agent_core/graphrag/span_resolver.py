"""Recover char-offset spans from worker-returned (document_id, text) contexts."""
from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ResolvedSpan:
    document_id: str
    start_char: int
    end_char: int
    snippet: str


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to a single space.

    Returns (normalized_text, raw_index) where raw_index[k] is the offset in
    `text` where normalized character k begins. raw_index has one extra
    trailing entry (len(text)) so an exclusive end index is always valid.
    """
    out: list[str] = []
    raw_idx: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            out.append(" ")
            raw_idx.append(i)
            while i < n and text[i].isspace():
                i += 1
        else:
            out.append(text[i])
            raw_idx.append(i)
            i += 1
    raw_idx.append(n)
    return "".join(out), raw_idx


def _recover_offsets(doc: str, text: str) -> tuple[int, int] | None:
    """Locate `text` within `doc`; return raw (start, end) offsets or None."""
    if not text or not text.strip():
        return None
    pos = doc.find(text)
    if pos != -1:
        return pos, pos + len(text)
    norm_doc, raw_idx = _normalized_with_map(doc)
    norm_text = _WS.sub(" ", text).strip()
    if not norm_text:
        return None
    npos = norm_doc.find(norm_text)
    if npos == -1:
        return None
    return raw_idx[npos], raw_idx[npos + len(norm_text)]


def resolve_spans(
    contexts: list[dict], corpus: dict[str, str],
) -> tuple[list[ResolvedSpan], int]:
    """Map [{document_id, text, score}] contexts to validated spans.

    Returns (spans, dropped) where `dropped` counts contexts whose document is
    unknown or whose text could not be located in the source document.
    """
    spans: list[ResolvedSpan] = []
    seen: set[tuple[str, int, int]] = set()
    dropped = 0
    for ctx in contexts:
        doc_id = ctx.get("document_id", "")
        text = ctx.get("text", "") or ""
        doc = corpus.get(doc_id)
        if doc is None:
            dropped += 1
            continue
        off = _recover_offsets(doc, text)
        if off is None:
            dropped += 1
            continue
        start, end = off
        key = (doc_id, start, end)
        if key in seen:
            continue
        seen.add(key)
        spans.append(ResolvedSpan(document_id=doc_id, start_char=start,
                                  end_char=end, snippet=doc[start:end]))
    return spans, dropped
