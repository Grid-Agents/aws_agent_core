"""Parse the vendored connection-application catalog into category lists.

Source of truth: ``review_seed/schema/{transmission,distribution}.md`` (copied
from the ``interactive-pages`` repo). Each markdown file has one ``## N. <Type>``
heading per connection type followed by a pipe-table whose columns are
``Category | What the developer submits | Why … | Source``. Storage is declared
as "same as Generation plus" a storage-specific table, so we merge them.

Note: the Storage section uses "Storage-specific addition" as the column-2
header instead of "What the developer submits". The loader reads column index 1
regardless of header name, so both formats work transparently.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "review_seed" / "schema"
CONN_TYPES = ("generation", "demand", "storage", "mixed")

_HEADING_RE = re.compile(r"^##\s+\d+\.\s+(.*)$")
_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def _heading_type(heading: str) -> str | None:
    low = heading.lower()
    return next((t for t in CONN_TYPES if low.startswith(t)), None)


def _parse_file(path: Path) -> dict[str, list[dict]]:
    """Return {conn_type: [{category, what_submitted, source}, ...]}."""
    by_type: dict[str, list[dict]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        h = _HEADING_RE.match(line)
        if h:
            current = _heading_type(h.group(1))
            if current is not None:
                by_type.setdefault(current, [])
            continue
        if current is None:
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 4:
            continue
        category = cells[0]
        # skip header rows (any header whose first cell is a known header name)
        # and separator rows (dashes/colons only)
        if not category or category.lower() in ("category",) or set(category) <= set("-: "):
            continue
        by_type[current].append(
            {"category": category, "what_submitted": cells[1], "source": cells[3]}
        )
    return by_type


@lru_cache(maxsize=4)
def _load_level(level: str) -> dict[str, list[dict]]:
    path = SCHEMA_DIR / f"{level}.md"
    if not path.is_file():
        raise KeyError(f"Unknown level: {level}")
    parsed = _parse_file(path)
    # Storage is documented as "Generation + storage-specific fields".
    if "generation" in parsed and "storage" in parsed:
        gen = parsed["generation"]
        seen = {c["category"] for c in gen}
        parsed["storage"] = gen + [c for c in parsed["storage"] if c["category"] not in seen]
    return parsed


def load_schema(level: str, conn_type: str) -> list[dict]:
    by_type = _load_level(level)
    if conn_type not in by_type:
        raise KeyError(f"Unknown connection type for {level}: {conn_type}")
    # Copy out of the lru_cache so callers can't mutate the cached list.
    return list(by_type[conn_type])
