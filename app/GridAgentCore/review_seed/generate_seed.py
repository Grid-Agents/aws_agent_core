"""Render the synthetic submission bundles in ``seed_data.py`` to PDF.

For every project this writes a bundle folder under
``review_seed/applications/{PROJECT_ID}/`` containing:

  * ``00_application_form.pdf`` — the filled application form. Each section is
    emitted with stable, line-anchored labels (``SECTION N:``, ``REQUIREMENT:``,
    ``SUBMITTED:``, ``SUPPORTING DOCS:``) so the backend can parse the PDF text
    back into structured sections at review time.
  * one PDF per supporting document (land lease, financial statement, etc.).

Run:  python review_seed/generate_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_data import PROJECTS  # noqa: E402

from grid_agent_core.application_form import render_application_form  # noqa: F401

APPLICATIONS_DIR = Path(__file__).resolve().parent / "applications"

INK = HexColor("#0f172a")
MUTED = HexColor("#475569")
ACCENT = HexColor("#0e7490")
LINE = HexColor("#cbd5e1")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    common = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT, leading=14)
    return {
        "title": ParagraphStyle(
            "title", base, fontName="Helvetica-Bold", fontSize=18, textColor=INK,
            leading=22, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", base, fontName="Helvetica", fontSize=10.5, textColor=MUTED,
            leading=14, spaceAfter=10,
        ),
        "meta": ParagraphStyle("meta", base, fontSize=10, leading=15, **{k: v for k, v in common.items() if k != "leading"}),
        "section": ParagraphStyle(
            "section", base, fontName="Helvetica-Bold", fontSize=12, textColor=ACCENT,
            leading=16, spaceBefore=12, spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label", base, fontName="Helvetica-Bold", fontSize=8.5, textColor=MUTED,
            leading=12, spaceBefore=4,
        ),
        "body": ParagraphStyle("body", base, fontSize=10, leading=14.5, textColor=INK, spaceAfter=2),
        "docpara": ParagraphStyle("docpara", base, fontSize=10, leading=15, textColor=INK, spaceAfter=8),
        "docheading": ParagraphStyle(
            "docheading", base, fontName="Helvetica-Bold", fontSize=10.5, textColor=INK,
            leading=14, spaceBefore=10, spaceAfter=3,
        ),
        "cell": ParagraphStyle("cell", base, fontSize=8.5, leading=11.5, textColor=INK),
        "cellhead": ParagraphStyle(
            "cellhead", base, fontName="Helvetica-Bold", fontSize=8.5, leading=11.5, textColor=colors.white,
        ),
        "sig": ParagraphStyle("sig", base, fontSize=9, leading=16, textColor=MUTED, spaceBefore=2),
    }


def _doc(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=path.stem,
    )


def _rule(color=LINE) -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.8, color=color, spaceBefore=6, spaceAfter=6)


def _ref_table(ref: dict, s: dict) -> Table:
    rows = [
        [Paragraph(f"<b>{k}</b>", s["cell"]), Paragraph(str(v), s["cell"])]
        for k, v in ref.items()
    ]
    t = Table(rows, colWidths=[42 * mm, 124 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _schedule_table(schedule: dict, s: dict) -> Table:
    cols = schedule["columns"]
    header = [Paragraph(c, s["cellhead"]) for c in cols]
    body = [[Paragraph(str(c), s["cell"]) for c in row] for row in schedule["rows"]]
    n = len(cols)
    width = 166 * mm
    t = Table([header, *body], colWidths=[width / n] * n, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#f6f8fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def render_support_doc(doc: dict, out: Path) -> None:
    s = _styles()
    flow = [
        Paragraph(doc["title"], s["title"]),
        Paragraph(doc.get("subtitle", ""), s["subtitle"]),
        _rule(ACCENT),
    ]

    if doc.get("ref"):
        flow.append(_ref_table(doc["ref"], s))
        flow.append(Spacer(1, 8))

    if doc.get("sections"):
        for sec in doc["sections"]:
            if sec.get("heading"):
                flow.append(Paragraph(sec["heading"], s["docheading"]))
            for para in sec.get("paras", []):
                flow.append(Paragraph(para, s["docpara"]))
    else:  # legacy flat paragraph list
        for para in doc.get("paras", []):
            flow.append(Paragraph(para, s["docpara"]))

    if doc.get("schedule"):
        sch = doc["schedule"]
        flow.append(Paragraph(sch.get("title", "Schedule"), s["docheading"]))
        flow.append(_schedule_table(sch, s))
        flow.append(Spacer(1, 6))

    if doc.get("execution"):
        flow.append(_rule())
        flow.append(Paragraph("EXECUTION", s["label"]))
        for line in doc["execution"]:
            flow.append(Paragraph(line, s["sig"]))

    _doc(out).build(flow)


def generate() -> None:
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    for project in PROJECTS:
        bundle = APPLICATIONS_DIR / project["id"]
        bundle.mkdir(parents=True, exist_ok=True)
        render_application_form(project, bundle / "00_application_form.pdf")
        for doc in project["documents"]:
            render_support_doc(doc, bundle / doc["filename"])
        print(f"  {project['id']}: form + {len(project['documents'])} supporting docs")
    print(f"Wrote {len(PROJECTS)} bundles to {APPLICATIONS_DIR}")


if __name__ == "__main__":
    generate()
