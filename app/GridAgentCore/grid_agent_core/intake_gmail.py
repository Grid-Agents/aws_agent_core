"""Gmail intake poller: pull unread attachment emails -> extract -> pending bundle.

Idempotent via a Gmail label (already-ingested messages are excluded by the
search query and labelled on success). The real googleapiclient service is built
in build_service(); all message logic takes the service as an argument so it is
unit-testable with a fake. Env-gated by settings.gmail_intake_enabled().
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Callable

from . import intake_store, settings
from .intake import extract_submission

log = logging.getLogger("grid.intake.gmail")

INGESTED_LABEL = "GridIntake/Ingested"
FAILED_LABEL = "GridIntake/Failed"
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _credentials():
    """Load Gmail OAuth credentials from a local token file (dev) or SSM (EC2).

    Prefers ``GRID_GMAIL_TOKEN_FILE`` when set (local dev); otherwise reads the
    token JSON from the SSM SecureString named by ``GRID_GMAIL_TOKEN_SSM_PARAM``.
    On EC2 the secret then stays in AWS and never lands on the instance disk; the
    refresh token is long-lived and access tokens refresh in memory each run.
    """
    from google.oauth2.credentials import Credentials

    path = settings.gmail_token_file()
    if path:
        return Credentials.from_authorized_user_file(path, _SCOPES)

    param = settings.gmail_token_ssm_param()
    if param:
        import json

        import boto3

        value = boto3.client("ssm", region_name=settings.aws_region()).get_parameter(
            Name=param, WithDecryption=True)["Parameter"]["Value"]
        return Credentials.from_authorized_user_info(json.loads(value), _SCOPES)

    raise RuntimeError(
        "no Gmail token source: set GRID_GMAIL_TOKEN_FILE or GRID_GMAIL_TOKEN_SSM_PARAM")


def build_service():  # pragma: no cover - thin googleapiclient wrapper
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def _header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _walk_parts(payload: dict):
    stack = [payload]
    while stack:
        part = stack.pop()
        for child in part.get("parts", []) or []:
            stack.append(child)
        yield part


def _fetch_attachment(service, message_id: str, attachment_id: str) -> bytes:  # pragma: no cover
    resp = (service.users().messages().attachments()
            .get(userId="me", messageId=message_id, id=attachment_id).execute())
    return base64.urlsafe_b64decode(resp["data"])


def _decode_body(payload: dict) -> str:
    for part in _walk_parts(payload):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
    return ""


def _ensure_label(service, name: str) -> str:  # pragma: no cover - network
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for lab in existing:
        if lab["name"] == name:
            return lab["id"]
    created = service.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow",
                            "messageListVisibility": "show"}).execute()
    return created["id"]


def _apply_label(service, message_id: str, label_name: str) -> None:
    try:
        label_id = _ensure_label(service, label_name)
    except Exception:  # in tests the fake has no labels(); fall back to raw name
        label_id = label_name
    service.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]}).execute()


def process_message(service, message: dict, *,
                    extractor: Callable[..., dict] = extract_submission,
                    text_reader: Callable[[bytes], str] | None = None) -> None:
    """Extract one Gmail message into a pending bundle and label it ingested."""
    from .review_api import _extract_text  # fitz-based PDF text extractor

    msg_id = message["id"]
    payload = message.get("payload", {})
    sender, subject = _header(message, "From"), _header(message, "Subject")
    body = _decode_body(payload)

    attachments: list[dict] = []         # for the extractor: {name, text}
    raw: list[tuple[str, bytes]] = []    # to persist: (name, bytes)
    for part in _walk_parts(payload):
        filename = part.get("filename") or ""
        att_id = part.get("body", {}).get("attachmentId")
        if not filename.lower().endswith(".pdf") or not att_id:
            continue
        data = _fetch_attachment(service, msg_id, att_id)
        raw.append((filename, data))
        if text_reader is not None:
            text = text_reader(data)
        else:  # pragma: no cover - real path writes a temp file for fitz
            import tempfile
            from pathlib import Path
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                tmp.write(data); tmp.flush()
                text = _extract_text(Path(tmp.name))
        attachments.append({"name": filename, "text": text})

    try:
        submission = extractor(attachments, body)
        intake_store.create_pending(msg_id, submission, raw, sender=sender, subject=subject)
        _apply_label(service, msg_id, INGESTED_LABEL)
    except Exception:
        log.exception("intake failed for message %s", msg_id)
        _apply_label(service, msg_id, FAILED_LABEL)


def poll_once(service) -> int:  # pragma: no cover - network glue
    listed = service.users().messages().list(
        userId="me", q=settings.gmail_query()).execute().get("messages", [])
    for ref in listed:
        full = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        process_message(service, full)
    return len(listed)


async def run_poller() -> None:  # pragma: no cover - background loop
    service = build_service()
    while True:
        try:
            n = await asyncio.to_thread(poll_once, service)
            if n:
                log.info("intake poll processed %d message(s)", n)
        except Exception:
            log.exception("intake poll error; backing off")
        await asyncio.sleep(settings.gmail_poll_seconds())


def start_intake_poller() -> asyncio.Task | None:  # pragma: no cover - wiring
    has_token = settings.gmail_token_file() or settings.gmail_token_ssm_param()
    if not settings.gmail_intake_enabled() or not has_token:
        log.info("Gmail intake disabled (set GRID_GMAIL_INTAKE=1 + "
                 "GRID_GMAIL_TOKEN_FILE or GRID_GMAIL_TOKEN_SSM_PARAM)")
        return None
    log.info("Gmail intake poller starting (every %ds)", settings.gmail_poll_seconds())
    return asyncio.create_task(run_poller())
