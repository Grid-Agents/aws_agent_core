from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest

from grid_agent_core.indexes import (
    build_all,
    build_graphrag_index,
    build_graphrag_prerequisites,
    build_vector_index,
    load_pageindex_hits,
)
from grid_agent_core.models import DocumentRecord, PageRecord
from grid_agent_core.corpus import write_manifest
from grid_agent_core.rag_compat.vector_rag import VectorRAG


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


def test_vector_index_reuses_cached_chunks(tmp_path, monkeypatch) -> None:
    _install_fake_sentence_transformers(monkeypatch)
    monkeypatch.setenv("GRID_VECTOR_RERANKER_ENABLED", "0")
    artifact_dir = write_graphrag_fixture(tmp_path)
    index_path = build_vector_index(
        artifact_dir,
        provider="sentence_transformers",
        chunk_strategy="fixed",
    )
    index_path.unlink()

    def fail_build_chunks(*_args, **_kwargs):
        pytest.fail("expected vector index to reuse the cached chunks")

    monkeypatch.setattr(VectorRAG, "_build_chunks", fail_build_chunks)

    resumed_path = build_vector_index(
        artifact_dir,
        provider="sentence_transformers",
        chunk_strategy="fixed",
    )

    assert resumed_path.exists()


def test_pageindex_query_rejects_custom_index_artifact(tmp_path) -> None:
    artifact_dir = write_graphrag_fixture(tmp_path)
    index_dir = artifact_dir / "indexes" / "pageindex"
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(
        json.dumps({"logic": "vector_pageindex_rag_eval.PageIndexRAG"}),
        encoding="utf-8",
    )
    (index_dir / "config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="official PageIndex adapter"):
        load_pageindex_hits(artifact_dir, "grid")


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


def _install_fake_sentence_transformers(monkeypatch) -> None:
    module = types.ModuleType("sentence_transformers")

    class SentenceTransformer:
        def __init__(self, _model_name: str):
            pass

        def encode(self, texts, **_kwargs):
            rows = []
            for text in texts:
                lowered = str(text).casefold()
                rows.append(
                    [
                        float("grid" in lowered),
                        float("document" in lowered),
                        float("text" in lowered),
                        1.0,
                    ]
                )
            values = np.asarray(rows, dtype=np.float32)
            norms = np.linalg.norm(values, axis=1, keepdims=True)
            return values / np.maximum(norms, 1e-12)

    class CrossEncoder:
        def __init__(self, _model_name: str):
            pass

        def predict(self, pairs):
            return [1.0 for _query, _document in pairs]

    module.SentenceTransformer = SentenceTransformer
    module.CrossEncoder = CrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
