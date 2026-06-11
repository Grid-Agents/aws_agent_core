from __future__ import annotations

import json

from fastapi.testclient import TestClient

from grid_agent_core import local_api


class FakeBody:
    def iter_lines(self):
        yield b'data: {"type":"trace","entry":{"kind":"agent","detail":"running"}}\n'
        yield b'data: {"type":"result","status":"completed"}\n'


class FakeClient:
    def __init__(self) -> None:
        self.request = {}

    def invoke_agent_runtime(self, **kwargs):
        self.request = kwargs
        return {"contentType": "text/event-stream", "response": FakeBody()}


def test_agentcore_proxy_streams_ndjson_and_keeps_session(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:runtime/grid")
    monkeypatch.setattr(local_api, "_agentcore_client", lambda: client)

    lines = list(
        local_api._agentcore_event_lines(
            {
                "prompt": "Gate 2?",
                "methods": ["find"],
                "runtime_session_id": "session-1",
            }
        )
    )

    assert json.loads(lines[0])["type"] == "trace"
    assert json.loads(lines[1])["type"] == "result"
    assert client.request["runtimeSessionId"] == "session-1"
    forwarded_payload = json.loads(client.request["payload"].decode("utf-8"))
    assert "runtime_session_id" not in forwarded_payload


def test_ui_serves_single_page_console_with_artifact_image_support() -> None:
    response = TestClient(local_api.app).get("/ui/")

    assert response.status_code == 200
    assert "SAMPLE_QUESTIONS" in response.text
    assert "hydrateAnswerImages" in response.text
    assert "/artifacts/" in response.text
