# tests/grid_agent_core/test_intake_store.py
from __future__ import annotations

import json

import grid_agent_core.intake_store as store


def _submission(level="transmission", conn_type="generation"):
    return {
        "id": "", "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
        "level": level, "conn_type": conn_type, "capacity": "300 MW", "status": "", "submitted": "",
        "sections": [
            {"id": "site", "title": "Site & location", "requirement": "Address + GPS.",
             "submitted": "Testfield Moor.", "docs": ["red_line.pdf"], "confidence": "high"},
        ],
        "documents": [{"name": "red_line.pdf"}],
        "intake": {"status": "extracted", "level_confidence": "high",
                   "flags": [], "unmapped_docs": []},
    }


def test_create_list_and_load_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")

    store.create_pending("msg-1", _submission(),
                         attachments=[("red_line.pdf", b"%PDF-1.4 fake")],
                         sender="dev@example.com", subject="Our application")

    listed = store.list_pending()
    assert len(listed) == 1
    assert listed[0]["id"] == "msg-1"
    assert listed[0]["sender"] == "dev@example.com"
    assert listed[0]["conn_type"] == "generation"

    detail = store.load_pending("msg-1")
    assert detail["sections"][0]["title"] == "Site & location"
    assert (store.PENDING_DIR / "msg-1" / "red_line.pdf").is_file()


def test_allocate_project_id_increments(tmp_path, monkeypatch):
    apps = tmp_path / "applications"
    (apps / "TX-GEN-001").mkdir(parents=True)
    (apps / "TX-GEN-004").mkdir()
    monkeypatch.setattr(store, "APPLICATIONS_DIR", apps)
    assert store.allocate_project_id("transmission", "generation") == "TX-GEN-005"
    assert store.allocate_project_id("distribution", "storage") == "DX-STO-001"


def test_accept_renders_form_and_moves_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    store.create_pending("msg-2", _submission(),
                         attachments=[("red_line.pdf", b"%PDF-1.4 fake")],
                         sender="dev@example.com", subject="App")

    project_id = store.accept_pending("msg-2")
    assert project_id == "TX-GEN-001"
    bundle = store.APPLICATIONS_DIR / project_id
    assert (bundle / "00_application_form.pdf").is_file()
    assert (bundle / "red_line.pdf").is_file()
    assert not (store.PENDING_DIR / "msg-2").exists()      # moved out of pending

    # the rendered form parses back through the real parser
    from grid_agent_core.review_api import parse_submission
    parsed = parse_submission(bundle)
    assert parsed["id"] == project_id
    assert parsed["sections"][0]["title"] == "Site & location"


def test_attachment_filename_preserved_on_disk(tmp_path, monkeypatch):
    """Attachments with spaces/parens must be written under their original basename."""
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")

    store.create_pending("msg-4", _submission(),
                         attachments=[("My Report.pdf", b"%PDF-1.4 fake")],
                         sender="dev@example.com", subject="Report")

    assert (store.PENDING_DIR / "msg-4" / "My Report.pdf").is_file()


def test_reject_archives_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    store.create_pending("msg-3", _submission(), attachments=[], sender="x@y.z", subject="s")
    store.reject_pending("msg-3", reason="incomplete")
    assert not (store.PENDING_DIR / "msg-3").exists()
    assert (store.PENDING_DIR / "_rejected" / "msg-3").exists()
