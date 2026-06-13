from __future__ import annotations

import pytest

from grid_agent_core.requirements_schema import load_schema, CONN_TYPES


def test_transmission_generation_has_core_categories():
    cats = load_schema("transmission", "generation")
    names = [c["category"] for c in cats]
    assert "Site & location" in names
    assert "Planning" in names
    assert "Company" in names
    # every category carries the source clause + the 'what submitted' guidance
    assert all(c["source"] for c in cats)
    assert all(c["what_submitted"] for c in cats)


def test_storage_includes_generation_plus_storage_fields():
    gen = {c["category"] for c in load_schema("transmission", "generation")}
    sto = {c["category"] for c in load_schema("transmission", "storage")}
    assert gen.issubset(sto)               # storage = generation + extras
    assert "Energy capacity" in sto


def test_distribution_generation_parses():
    cats = load_schema("distribution", "generation")
    names = [c["category"] for c in cats]
    assert len(cats) >= 8
    assert "Applicant" in names   # real row in distribution.md "## 1. Generation"


def test_unknown_type_raises():
    with pytest.raises(KeyError):
        load_schema("transmission", "banana")


def test_unknown_level_raises():
    with pytest.raises(KeyError):
        load_schema("nonexistent", "generation")


def test_conn_types_constant():
    assert set(CONN_TYPES) == {"generation", "demand", "storage", "mixed"}
