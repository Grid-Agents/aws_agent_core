from __future__ import annotations

import pytest

import json

from grid_agent_core.indexes import (
    build_all,
    build_graphrag_index,
    build_graphrag_prerequisites,
    build_vector_index,
)
from grid_agent_core.models import DocumentRecord, PageRecord
from grid_agent_core.corpus import write_manifest


def test_graphrag_prerequisites_are_local_artifacts(tmp_path) -> None:
    artifact_dir = write_graphrag_fixture(tmp_path)

    data_dir = build_graphrag_prerequisites(artifact_dir)

    corpus = json.loads((data_dir / "graph_index" / "corpus.json").read_text(encoding="utf-8"))
    chunks = json.loads((data_dir / "graph_index" / "canonical_chunks.json").read_text(encoding="utf-8"))
    assert "grid/doc.txt" in corpus
    assert chunks[0]["document_id"] == "grid/doc.txt"


def test_graphrag_dependency_error_is_clear(tmp_path, monkeypatch) -> None:
    artifact_dir = write_graphrag_fixture(tmp_path)
    monkeypatch.setattr("grid_agent_core.indexes._missing_graphrag_dependencies", lambda: ["graphrag"])

    with pytest.raises(RuntimeError, match="GraphRAG Python dependencies are missing"):
        build_graphrag_index(artifact_dir)


def test_build_all_requires_parsed_corpus(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="grid-parse-documents"):
        build_all(tmp_path / "artifacts", methods=["vector"])


def test_vector_index_resumes_document_parts(tmp_path, monkeypatch) -> None:
    artifact_dir = write_graphrag_fixture(tmp_path)
    index_path = build_vector_index(artifact_dir, provider="local")
    index_path.unlink()

    def fail_make_chunks(*_args, **_kwargs):
        pytest.fail("expected vector index to reuse the document part")

    monkeypatch.setattr("grid_agent_core.indexes.make_chunks", fail_make_chunks)

    resumed_path = build_vector_index(artifact_dir, provider="local")

    assert resumed_path.exists()


def write_graphrag_fixture(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    text_dir = artifact_dir / "corpus" / "grid"
    text_dir.mkdir(parents=True)
    (text_dir / "doc.txt").write_text("Grid document text", encoding="utf-8")
    write_manifest(
        artifact_dir,
        [
            DocumentRecord(
                document_id="grid/doc.txt",
                title="Doc",
                category="Category",
                filename="doc.pdf",
                source_path="raw/doc.pdf",
                text_path="corpus/grid/doc.txt",
                source_sha256="s",
                text_sha256="t",
                pages=[PageRecord(page=1, start_char=0, end_char=18, text_sha256="p")],
            )
        ],
    )
    return artifact_dir
