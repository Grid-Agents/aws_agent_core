"""Vendored rlm-eval sentence splitter used by GraphRAG canonical chunks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pysbd


_PYSBD_SEGMENTER = pysbd.Segmenter(language="en", clean=False, char_span=True)


def _pysbd_cache_dir() -> "Path | None":
    """Return the directory used to cache pysbd output, or None if disabled.

    Defaults to ``.cache/pysbd`` in the current working directory; override
    with the ``RLM_EVAL_PYSBD_CACHE`` environment variable. Set the variable
    to an empty string to disable caching.
    """
    env = os.environ.get("RLM_EVAL_PYSBD_CACHE", ".cache/pysbd")
    if env == "":
        return None
    p = Path(env)
    p.mkdir(parents=True, exist_ok=True)
    return p


def split_into_sentences(text, *, return_spans=False):
    """Sentence-split using pysbd, which handles legal abbreviations correctly.

    Returns plain strings by default, or (start_char, end_char, sentence) triples
    when return_spans=True. Results are cached to disk keyed by SHA-256 of the
    input text - pysbd is ~1000x slower than naive regex on legal documents
    (~0.14s per 50KB doc), so a per-doc cache makes the second-and-onwards
    chunking pass essentially free.
    """
    if not text:
        return []

    cache_dir = _pysbd_cache_dir()
    cache_path = None
    if cache_dir is not None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cache_path = cache_dir / f"{digest}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            if return_spans:
                return [(int(s[0]), int(s[1]), s[2]) for s in cached]
            return [s[2] for s in cached]

    raw = _PYSBD_SEGMENTER.segment(text)
    triples = [[int(s.start), int(s.end), s.sent] for s in raw]
    if cache_path is not None:
        try:
            cache_path.write_text(json.dumps(triples))
        except OSError:
            pass  # cache failure must not break the splitter

    if return_spans:
        return [(t[0], t[1], t[2]) for t in triples]
    return [t[2] for t in triples]


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Return [(start_char, end_char, sentence_text)] with offsets into `text`.

    Trims leading/trailing whitespace from each sentence; keeps the closing
    punctuation. Routes through pysbd (via `split_into_sentences`) so legal
    abbreviations like ``Sec.``, ``Inc.``, ``U.S.``, ``LLC.`` no longer
    trigger spurious splits.
    """
    if not text:
        return []
    out: list[tuple[int, int, str]] = []
    for s, e, _sent in split_into_sentences(text, return_spans=True):
        # Trim leading/trailing whitespace from the span so callers see
        # offsets that round-trip to the source text and chunk-text strings
        # don't carry stray spaces. pysbd's char_span often includes the
        # trailing space after the period.
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if s < e:
            out.append((s, e, text[s:e]))
    return out
