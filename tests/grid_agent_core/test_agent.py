from __future__ import annotations

import asyncio

from grid_agent_core.agent import GridAgentSession, normalize_methods
from grid_agent_core.models import Evidence


class FakeRepository:
    def __init__(self, image_path=None) -> None:
        self.image_path = image_path

    def search(self, method, query, *, top_k):
        metadata = {}
        if self.image_path is not None:
            metadata["figures"] = [
                {
                    "figure_id": "grid/doc#fig0001",
                    "page": 3,
                    "description": "Gate 2 figure",
                    "local_path": str(self.image_path),
                    "content_type": "image/png",
                }
            ]
        return [
            Evidence(
                id="",
                document_id="grid/doc.txt",
                title="Grid Code",
                category="02 - Industry Codes",
                source_path="raw/doc.pdf",
                page=3,
                section="Section",
                span_text=f"{method}: {query}",
                score=0.9,
                artifact_source=method,
                start_char=10,
                end_char=40,
                metadata=metadata,
            )
        ]


def test_normalize_methods_defaults_and_validates() -> None:
    assert normalize_methods(None) == ["vector", "pageindex", "find"]
    assert normalize_methods(["graphrag"]) == ["graphrag"]
    try:
        normalize_methods(["bad"])
    except ValueError as exc:
        assert "Unsupported retrieval method" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_session_search_and_subagent_payload_metadata(tmp_path) -> None:
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    session = GridAgentSession(
        "What is Gate 2?",
        methods=["find"],
        enable_subagents=False,
        artifacts_path=tmp_path,
        repository=FakeRepository(image_path),
    )

    content, is_error = asyncio.run(session.search("find", "Gate 2"))
    asyncio.run(session.cite("E1"))
    final = session.final_event()

    assert not is_error
    assert "Gate 2" in content[0]["text"]
    assert any(block["type"] == "image" for block in content)
    assert final["enable_subagents"] is False
    assert final["citations"][0]["id"] == "E1"
    assert final["citations"][0]["metadata"]["figures"][0]["figure_id"] == "grid/doc#fig0001"
    assert final["trajectory"][0]["kind"] == "retrieval"
