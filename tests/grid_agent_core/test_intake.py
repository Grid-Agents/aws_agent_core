from __future__ import annotations

from grid_agent_core.intake import extract_submission


class FakeModel:
    """Returns queued tool-call dicts, one per call_tool invocation."""
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def call_tool(self, *, system, user, tool_name, input_schema):
        self.calls.append({"system": system, "user": user, "tool_name": tool_name})
        return self._responses.pop(0)


def test_extract_builds_submission_with_requirements_from_schema():
    model = FakeModel(
        # call A: classification
        {"level": "transmission", "conn_type": "generation", "level_confidence": "high",
         "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
         "capacity": "300 MW onshore wind"},
        # call B: per-category extraction (subset of categories returned)
        {"sections": [
            {"category": "Site & location", "submitted": "Testfield Moor, 54.0N -0.5E",
             "docs": ["red_line.pdf"], "confidence": "high"},
            {"category": "Planning", "submitted": "", "docs": [], "confidence": "low"},
         ],
         "flags": ["No planning evidence found"],
         "unmapped_docs": ["random.pdf"]},
    )
    attachments = [
        {"name": "red_line.pdf", "text": "Red line boundary plan for Testfield Moor."},
        {"name": "random.pdf", "text": "Unrelated."},
    ]
    result = extract_submission(attachments, body="Please find our application attached.",
                                model=model)

    assert result["level"] == "transmission"
    assert result["conn_type"] == "generation"
    assert result["name"] == "Testfield Wind"
    # requirement text comes from the SCHEMA, not the model
    site = next(s for s in result["sections"] if s["title"] == "Site & location")
    assert "GPS coordinates" in site["requirement"]
    assert site["submitted"] == "Testfield Moor, 54.0N -0.5E"
    assert site["docs"] == ["red_line.pdf"]
    assert site["confidence"] == "high"
    # intake block carries flags + provenance
    assert "No planning evidence found" in result["intake"]["flags"]
    assert result["intake"]["unmapped_docs"] == ["random.pdf"]
    assert result["intake"]["level_confidence"] == "high"
    # two model calls were made
    assert [c["tool_name"] for c in model.calls] == ["classify", "extract"]


def test_extract_marks_failure_when_classification_raises():
    class Boom:
        def call_tool(self, **_):
            raise RuntimeError("model down")
    result = extract_submission([{"name": "a.pdf", "text": "x"}], body="", model=Boom())
    assert result["intake"]["status"] == "extraction_failed"
    assert result["sections"] == []
    assert result["documents"] == [{"name": "a.pdf"}]


def test_extract_marks_failure_on_unknown_classification():
    model = FakeModel(
        # call A: classification returns an invalid level the schema can't load
        {"level": "sub-transmission", "conn_type": "generation", "level_confidence": "high",
         "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
         "capacity": "300 MW onshore wind"},
    )
    result = extract_submission([{"name": "a.pdf", "text": "x"}], body="", model=model)
    assert result["intake"]["status"] == "extraction_failed"
    assert result["sections"] == []


def test_extract_matches_categories_despite_formatting_drift():
    """The model is non-deterministic about category formatting; a present
    answer must not be silently dropped over dash/case/'&' differences."""
    model = FakeModel(
        {"level": "transmission", "conn_type": "generation", "level_confidence": "high",
         "name": "Driftfield", "applicant": "Drift Ltd", "capacity": "100 MW"},
        {"sections": [
            # schema is 'Site & location' / 'Land — area' — model returns drifted forms
            {"category": "site and location", "submitted": "At the moor.",
             "docs": [], "confidence": "high"},
            {"category": "Land - area", "submitted": "310 ha red line.",
             "docs": [], "confidence": "medium"},
         ], "flags": [], "unmapped_docs": []},
    )
    result = extract_submission([{"name": "a.pdf", "text": "x"}], body="", model=model)
    site = next(s for s in result["sections"] if s["title"] == "Site & location")
    land = next(s for s in result["sections"] if s["title"] == "Land — area")
    assert site["submitted"] == "At the moor."          # matched despite '&'/case
    assert land["submitted"] == "310 ha red line."      # matched despite '-' vs '—'
