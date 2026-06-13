# tests/grid_agent_core/test_application_form.py
from __future__ import annotations

from grid_agent_core.application_form import render_application_form
from grid_agent_core.review_api import parse_submission

PROJECT = {
    "id": "TX-GEN-009",
    "name": "Testfield Wind",
    "applicant": "Testfield Renewables Ltd",
    "level": "transmission",
    "conn_type": "generation",
    "capacity": "300 MW onshore wind",
    "status": "Under review",
    "submitted": "2026-06-13",
    "sections": [
        {
            "id": "s1",
            "title": "Site & location",
            "requirement": "Site address plus GPS coordinates (WGS84, 3 d.p.).",
            "submitted": "Testfield Moor, 54.0 N, -0.5 E. Connects to the 400 kV corridor.",
            "docs": ["red_line_boundary_plan.pdf"],
        },
        {
            "id": "s2",
            "title": "Project capacity",
            "requirement": "Megawatt capacity plus total connection capacity requested.",
            "submitted": "Total TEC requested: 300 MW. 60 x 5 MW turbines.",
            "docs": [],
        },
    ],
}


def test_render_then_parse_round_trips(tmp_path):
    out = tmp_path / "00_application_form.pdf"
    render_application_form(PROJECT, out)
    assert out.is_file()

    parsed = parse_submission(tmp_path)
    assert parsed["id"] == "TX-GEN-009"
    assert parsed["name"] == "Testfield Wind"
    assert parsed["level"] == "transmission"
    assert parsed["conn_type"] == "generation"
    titles = [s["title"] for s in parsed["sections"]]
    assert titles == ["Site & location", "Project capacity"]
    assert parsed["sections"][0]["docs"] == ["red_line_boundary_plan.pdf"]
    assert parsed["sections"][1]["docs"] == []
    assert "GPS coordinates" in parsed["sections"][0]["requirement"]
