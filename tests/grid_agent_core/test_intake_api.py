# tests/grid_agent_core/test_intake_api.py
from __future__ import annotations

from fastapi.testclient import TestClient

import grid_agent_core.intake_store as store
from grid_agent_core import local_api


def _seed_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    submission = {
        "id": "", "name": "Testfield Wind", "applicant": "Testfield Renewables Ltd",
        "level": "transmission", "conn_type": "generation", "capacity": "300 MW",
        "status": "", "submitted": "",
        "sections": [{"id": "site", "title": "Site & location", "requirement": "Address + GPS.",
                      "submitted": "Testfield Moor.", "docs": [], "confidence": "high"}],
        "documents": [], "intake": {"status": "extracted", "level_confidence": "high",
                                    "flags": ["check planning"], "unmapped_docs": []},
    }
    store.create_pending("msg-1", submission, attachments=[],
                         sender="dev@example.com", subject="Application")


def test_list_and_get_intake(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)

    r = client.get("/api/review/intake")
    assert r.status_code == 200
    items = r.json()["pending"]
    assert items[0]["id"] == "msg-1"
    assert items[0]["flag_count"] == 1

    r = client.get("/api/review/intake/msg-1")
    assert r.status_code == 200
    detail = r.json()
    assert detail["sections"][0]["title"] == "Site & location"
    assert detail["intake"]["flags"] == ["check planning"]


def test_accept_promotes_to_project(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    r = client.post("/api/review/intake/msg-1/accept")
    assert r.status_code == 200
    assert r.json()["project_id"] == "TX-GEN-001"
    assert (store.APPLICATIONS_DIR / "TX-GEN-001" / "00_application_form.pdf").is_file()


def test_reject_removes_from_queue(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    r = client.post("/api/review/intake/msg-1/reject", json={"reason": "incomplete"})
    assert r.status_code == 200
    assert client.get("/api/review/intake").json()["pending"] == []


def test_get_unknown_intake_404(monkeypatch, tmp_path):
    _seed_pending(monkeypatch, tmp_path)
    client = TestClient(local_api.app)
    assert client.get("/api/review/intake/nope").status_code == 404


def test_accept_extraction_failed_returns_409(monkeypatch, tmp_path):
    """Accepting an extraction_failed record (empty level/conn_type) must give 409, not 404."""
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    failed_submission = {
        "id": "", "name": "Unknown", "applicant": "",
        "level": "", "conn_type": "", "capacity": "", "status": "", "submitted": "",
        "sections": [], "documents": [],
        "intake": {"status": "extraction_failed", "level_confidence": "",
                   "flags": [], "unmapped_docs": []},
    }
    store.create_pending("msg-fail", failed_submission, attachments=[],
                         sender="bad@example.com", subject="Unreadable")
    client = TestClient(local_api.app)
    r = client.post("/api/review/intake/msg-fail/accept")
    assert r.status_code == 409
