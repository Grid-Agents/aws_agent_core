# tests/grid_agent_core/test_intake_gmail.py
from __future__ import annotations

import base64

import grid_agent_core.intake_store as store
from grid_agent_core.intake_gmail import process_message, INGESTED_LABEL


class FakeExtractor:
    def __call__(self, attachments, body, model=None):
        return {
            "id": "", "name": "Testfield Wind", "applicant": "T Ltd",
            "level": "transmission", "conn_type": "generation", "capacity": "300 MW",
            "status": "", "submitted": "",
            "sections": [], "documents": [{"name": a["name"]} for a in attachments],
            "intake": {"status": "extracted", "level_confidence": "high",
                       "flags": [], "unmapped_docs": []},
        }


class FakeGmail:
    """Minimal stand-in for the googleapiclient Gmail service."""
    def __init__(self, message):
        self._message = message
        self.labelled = []
        self.attachment = base64.urlsafe_b64encode(b"%PDF-1.4 fake").decode()

    # service.users().messages().get(...).execute()
    def users(self):
        return self
    def messages(self):
        return self
    def get(self, userId, id, format=None):
        return _Exec(self._message)
    def attachments(self):
        return self
    def _att_get(self, userId, messageId, id):
        return _Exec({"data": self.attachment})
    def modify(self, userId, id, body):
        self.labelled.append((id, body))
        return _Exec({})


class _Exec:
    def __init__(self, val): self._val = val
    def execute(self): return self._val


def _message():
    return {
        "id": "msg-42",
        "payload": {
            "headers": [{"name": "From", "value": "dev@example.com"},
                        {"name": "Subject", "value": "Our application"}],
            "parts": [
                {"mimeType": "text/plain",
                 "body": {"data": base64.urlsafe_b64encode(b"See attached.").decode()}},
                {"mimeType": "application/pdf", "filename": "red_line.pdf",
                 "body": {"attachmentId": "att-1"}},
            ],
        },
    }


def test_process_message_creates_pending_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(store, "APPLICATIONS_DIR", tmp_path / "applications")
    gmail = FakeGmail(_message())
    # patch the attachment fetch indirection used by process_message
    monkeypatch.setattr("grid_agent_core.intake_gmail._fetch_attachment",
                        lambda svc, mid, aid: b"%PDF-1.4 fake")

    process_message(gmail, _message(), extractor=FakeExtractor(),
                    text_reader=lambda data: "Red line plan text")

    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == "msg-42"
    assert pending[0]["sender"] == "dev@example.com"
    assert (store.PENDING_DIR / "msg-42" / "red_line.pdf").is_file()
    # message was labelled ingested (idempotency marker)
    assert gmail.labelled and gmail.labelled[0][0] == "msg-42"


import json as _json

import pytest

from grid_agent_core import intake_gmail

_TOKEN = {"refresh_token": "rt-123", "client_id": "cid", "client_secret": "sec",
          "token_uri": "https://oauth2.googleapis.com/token"}


def test_credentials_from_file(tmp_path, monkeypatch):
    p = tmp_path / "tok.json"; p.write_text(_json.dumps(_TOKEN))
    monkeypatch.setenv("GRID_GMAIL_TOKEN_FILE", str(p))
    monkeypatch.delenv("GRID_GMAIL_TOKEN_SSM_PARAM", raising=False)
    assert intake_gmail._credentials().refresh_token == "rt-123"


def test_credentials_from_ssm(monkeypatch):
    monkeypatch.delenv("GRID_GMAIL_TOKEN_FILE", raising=False)
    monkeypatch.setenv("GRID_GMAIL_TOKEN_SSM_PARAM", "/grid-bff/gmail-token")

    class FakeSSM:
        def get_parameter(self, **kw):
            assert kw["Name"] == "/grid-bff/gmail-token" and kw["WithDecryption"] is True
            return {"Parameter": {"Value": _json.dumps(_TOKEN)}}

    monkeypatch.setattr("boto3.client", lambda *a, **k: FakeSSM())
    assert intake_gmail._credentials().refresh_token == "rt-123"


def test_credentials_no_source_raises(monkeypatch):
    monkeypatch.delenv("GRID_GMAIL_TOKEN_FILE", raising=False)
    monkeypatch.delenv("GRID_GMAIL_TOKEN_SSM_PARAM", raising=False)
    with pytest.raises(RuntimeError):
        intake_gmail._credentials()
