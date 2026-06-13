"""Filesystem store for pending email submissions + Accept/Reject.

Pending bundles live under review_seed/pending/{intake_id}/ as submission.json
(the extracted dict + sender/subject) plus the original attachment PDFs. Accept
allocates a project id, renders 00_application_form.pdf, and moves the bundle
into review_seed/applications/ where the existing review pipeline picks it up.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .application_form import render_application_form

_SEED = Path(__file__).resolve().parents[1] / "review_seed"
PENDING_DIR = _SEED / "pending"
APPLICATIONS_DIR = _SEED / "applications"

_LEVEL_CODE = {"transmission": "TX", "distribution": "DX"}
_TYPE_CODE = {"generation": "GEN", "demand": "DEM", "storage": "STO", "mixed": "MIX"}
_SUBMISSION_FILE = "submission.json"


def _safe_id(intake_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", intake_id)


def create_pending(intake_id: str, submission: dict[str, Any],
                   attachments: list[tuple[str, bytes]], *, sender: str, subject: str) -> Path:
    dest = PENDING_DIR / _safe_id(intake_id)
    dest.mkdir(parents=True, exist_ok=True)
    record = {**submission, "intake": {**submission.get("intake", {}),
                                       "sender": sender, "subject": subject,
                                       "intake_id": intake_id}}
    (dest / _SUBMISSION_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2))
    for name, data in attachments:
        (dest / _safe_id(name)).write_bytes(data)
    return dest


def load_pending(intake_id: str) -> dict[str, Any]:
    path = PENDING_DIR / _safe_id(intake_id) / _SUBMISSION_FILE
    if not path.is_file():
        raise KeyError(f"Unknown pending intake: {intake_id}")
    return json.loads(path.read_text())


def list_pending() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not PENDING_DIR.is_dir():
        return out
    for d in sorted(PENDING_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        sub = d / _SUBMISSION_FILE
        if not sub.is_file():
            continue
        rec = json.loads(sub.read_text())
        intake = rec.get("intake", {})
        out.append({
            "id": intake.get("intake_id", d.name),
            "name": rec.get("name", ""), "applicant": rec.get("applicant", ""),
            "level": rec.get("level", ""), "conn_type": rec.get("conn_type", ""),
            "sender": intake.get("sender", ""), "subject": intake.get("subject", ""),
            "status": intake.get("status", "extracted"),
            "section_count": len(rec.get("sections", [])),
            "flag_count": len(intake.get("flags", [])),
        })
    return out


def allocate_project_id(level: str, conn_type: str) -> str:
    prefix = f"{_LEVEL_CODE[level]}-{_TYPE_CODE[conn_type]}-"
    pat = re.compile(re.escape(prefix) + r"(\d+)$")
    nums = [int(m.group(1)) for d in APPLICATIONS_DIR.glob(f"{prefix}*")
            if (m := pat.match(d.name))] if APPLICATIONS_DIR.is_dir() else []
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def accept_pending(intake_id: str) -> str:
    src = PENDING_DIR / _safe_id(intake_id)
    rec = load_pending(intake_id)
    project_id = allocate_project_id(rec["level"], rec["conn_type"])
    dest = APPLICATIONS_DIR / project_id
    dest.mkdir(parents=True, exist_ok=True)
    project = {**rec, "id": project_id, "status": "Under review"}
    render_application_form(project, dest / "00_application_form.pdf")
    for pdf in src.glob("*.pdf"):
        shutil.copy2(pdf, dest / pdf.name)
    shutil.rmtree(src)
    return project_id


def reject_pending(intake_id: str, reason: str | None = None) -> None:
    src = PENDING_DIR / _safe_id(intake_id)
    if not src.is_dir():
        raise KeyError(f"Unknown pending intake: {intake_id}")
    if reason:
        (src / "reject_reason.txt").write_text(reason)
    archive = PENDING_DIR / "_rejected" / _safe_id(intake_id)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        shutil.rmtree(archive)
    shutil.move(str(src), str(archive))
