# grid_agent_core/application_form.py
"""Render a submission dict to the line-anchored ``00_application_form.pdf``.

Extracted from ``review_seed/generate_seed.py`` so both the seed generator and
the email-intake Accept flow render the identical parseable layout (the labels
``PROJECT ID:`` / ``SECTION N:`` / ``REQUIREMENT:`` / ``SUBMITTED:`` /
``SUPPORTING DOCS:`` that ``review_api.parse_submission`` reads back).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

INK = HexColor("#0f172a")
MUTED = HexColor("#475569")
ACCENT = HexColor("#0e7490")
LINE = HexColor("#cbd5e1")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("title", base, fontName="Helvetica-Bold", fontSize=18,
                                textColor=INK, leading=22, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", base, fontName="Helvetica", fontSize=10.5,
                                   textColor=MUTED, leading=14, spaceAfter=10),
        "meta": ParagraphStyle("meta", base, fontName="Helvetica", fontSize=10, leading=15,
                               textColor=INK, alignment=TA_LEFT),
        "section": ParagraphStyle("section", base, fontName="Helvetica-Bold", fontSize=12,
                                  textColor=ACCENT, leading=16, spaceBefore=12, spaceAfter=4),
        "label": ParagraphStyle("label", base, fontName="Helvetica-Bold", fontSize=8.5,
                                textColor=MUTED, leading=12, spaceBefore=4),
        "body": ParagraphStyle("body", base, fontName="Helvetica", fontSize=10, leading=14.5,
                               textColor=INK, spaceAfter=2),
    }


def _doc(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=path.stem,
    )


def _rule(color=LINE) -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.8, color=color, spaceBefore=6, spaceAfter=6)


def render_application_form(project: dict, out: Path) -> None:
    s = _styles()
    flow = [
        Paragraph("Grid Interconnection Application Form", s["title"]),
        Paragraph(f"{project['level'].capitalize()} connection &mdash; {project['conn_type']}",
                  s["subtitle"]),
        _rule(ACCENT),
    ]
    meta = [
        ("PROJECT ID", project["id"]), ("PROJECT NAME", project["name"]),
        ("APPLICANT", project["applicant"]), ("LEVEL", project["level"]),
        ("CONNECTION TYPE", project["conn_type"]), ("CAPACITY", project["capacity"]),
        ("STATUS", project["status"]), ("DATE SUBMITTED", project["submitted"]),
    ]
    for label, value in meta:
        flow.append(Paragraph(f"<b>{label}:</b> {value}", s["meta"]))
    flow.append(_rule())
    for i, sec in enumerate(project["sections"], start=1):
        docs = ", ".join(sec["docs"]) if sec["docs"] else "none"
        flow.append(Paragraph(f"SECTION {i}: {sec['title']}", s["section"]))
        flow.append(Paragraph("REQUIREMENT:", s["label"]))
        flow.append(Paragraph(sec["requirement"], s["body"]))
        flow.append(Paragraph("SUBMITTED:", s["label"]))
        flow.append(Paragraph(sec["submitted"], s["body"]))
        flow.append(Paragraph("SUPPORTING DOCS:", s["label"]))
        flow.append(Paragraph(docs, s["body"]))
        flow.append(Spacer(1, 2))
    _doc(out).build(flow)
