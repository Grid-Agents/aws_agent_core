from __future__ import annotations

import json
import base64
import sys
import types
from types import SimpleNamespace

import numpy as np

from grid_agent_core.colivara import build_colivara_index, load_colivara_hits
from grid_agent_core.corpus import write_manifest
from grid_agent_core.indexes import build_pageindex, build_vector_index
from grid_agent_core.models import DocumentRecord, FigureRecord, PageRecord
from grid_agent_core.rag_compat.llm import FakeLLM
from grid_agent_core.retrieval import GridRetrievalRepository


async def fake_md_to_tree(**_kwargs):
    return {
        "doc_name": "doc",
        "doc_description": "Gate readiness and queue management document.",
        "line_count": 6,
        "structure": [
            {
                "title": "grid/doc.txt",
                "node_id": "0000",
                "line_num": 1,
                "summary": "Gate readiness and queue management",
                "nodes": [
                    {
                        "title": "Virtual page 1",
                        "node_id": "0001",
                        "line_num": 3,
                        "summary": "Gate readiness and CNDM queue management",
                    }
                ],
            }
        ],
    }


def write_artifact_fixture(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    text_dir = artifact_dir / "corpus" / "grid"
    text_dir.mkdir(parents=True)
    raw_dir = artifact_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    text = "[Page 1]\nGate 2 evidence must show land rights and readiness.\n[Page 2]\nQueue management follows the CNDM process.\n"
    text_path = text_dir / "doc.txt"
    text_path.write_text(text, encoding="utf-8")
    figure_dir = artifact_dir / "figures" / "grid" / "doc"
    figure_dir.mkdir(parents=True)
    (figure_dir / "gate-2.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    record = DocumentRecord(
        document_id="grid/doc.txt",
        title="Gate 2 Criteria",
        category="05 - Connections Reform (TMO4+)",
        filename="doc.pdf",
        source_path="raw/doc.pdf",
        text_path="corpus/grid/doc.txt",
        source_sha256="source",
        text_sha256="text",
        pages=[
            PageRecord(page=1, start_char=0, end_char=text.index("[Page 2]"), text_sha256="p1"),
            PageRecord(page=2, start_char=text.index("[Page 2]"), end_char=len(text), text_sha256="p2"),
        ],
        figures=[
            FigureRecord(
                figure_id="grid/doc#fig0001",
                page=1,
                description="Gate 2 readiness diagram",
                image_path="figures/grid/doc/gate-2.png",
                image_sha256="4c4b6a3b6c40d99661317a10dcac4e13fc762a6f146e8c8f7e3b9e2cb467ff31",
                filename="gate-2.png",
                content_type="image/png",
                size_bytes=8,
                category="figure_crop",
                start_char=0,
                end_char=text.index("[Page 2]"),
                bbox={"unit": "page_fraction", "x": 0.1, "y": 0.2, "w": 0.7, "h": 0.3},
            )
        ],
    )
    write_manifest(artifact_dir, [record])
    return artifact_dir


class FakeColiVaraClient:
    def __init__(self) -> None:
        self.upserts = []

    def upsert_document(self, **kwargs):
        self.upserts.append(kwargs)
        return {"id": 7, "num_pages": 2}

    def search(self, **kwargs):
        return {
            "query": kwargs["query"],
            "results": [
                {
                    "collection_name": kwargs["collection_name"],
                    "document_name": self.upserts[0]["name"],
                    "document_metadata": {
                        "grid_document_id": "grid/doc.txt",
                        "title": "Gate 2 Criteria",
                    },
                    "page_number": 1,
                    "raw_score": 18.0,
                    "normalized_score": 0.87,
                    "img_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode("ascii"),
                }
            ],
        }


def test_exact_find_returns_normalized_evidence(tmp_path) -> None:
    artifact_dir = write_artifact_fixture(tmp_path)
    repo = GridRetrievalRepository(artifact_dir)

    evidence = repo.search("find", "land rights")

    assert evidence
    assert evidence[0].document_id == "grid/doc.txt"
    assert evidence[0].title == "Gate 2 Criteria"
    assert evidence[0].page == 1
    assert evidence[0].artifact_source == "find"
    assert "land rights" in evidence[0].span_text
    assert evidence[0].metadata["figures"][0]["figure_id"] == "grid/doc#fig0001"
    assert evidence[0].metadata["figures"][0]["category"] == "figure_crop"
    assert evidence[0].metadata["figures"][0]["bbox"]["unit"] == "page_fraction"


def test_retrieval_adds_s3_figure_uri(tmp_path, monkeypatch) -> None:
    artifact_dir = write_artifact_fixture(tmp_path)
    monkeypatch.setenv("GRID_S3_BUCKET", "bucket")
    monkeypatch.setenv("GRID_S3_PREFIX", "prefix")
    repo = GridRetrievalRepository(artifact_dir)

    evidence = repo.search("find", "land rights")

    figure = evidence[0].metadata["figures"][0]
    assert figure["local_path"].endswith("figures/grid/doc/gate-2.png")
    assert figure["s3_uri"] == "s3://bucket/prefix/figures/grid/doc/gate-2.png"


def test_colivara_sync_and_hits_return_visual_page(tmp_path) -> None:
    artifact_dir = write_artifact_fixture(tmp_path)
    client = FakeColiVaraClient()

    index_path = build_colivara_index(
        artifact_dir,
        collection_name="grid-test",
        client=client,
        wait=True,
    )
    hits = load_colivara_hits(
        artifact_dir,
        "Gate 2 visual evidence",
        top_k=1,
        client=client,
    )

    assert index_path.exists()
    assert client.upserts[0]["collection_name"] == "grid-test"
    assert client.upserts[0]["metadata"]["grid_document_id"] == "grid/doc.txt"
    assert hits[0].source == "colivara"
    assert hits[0].document_id == "grid/doc.txt"
    assert hits[0].score == 0.87
    assert "Parsed page text" in hits[0].text
    figure = hits[0].metadata["figures"][0]
    assert figure["category"] == "colivara_page"
    assert (artifact_dir / figure["image_path"]).exists()


def test_vector_and_pageindex_indexes_are_queryable(tmp_path, monkeypatch) -> None:
    _install_fake_sentence_transformers(monkeypatch)
    monkeypatch.setenv("GRID_VECTOR_RERANKER_ENABLED", "0")
    monkeypatch.setenv("GRID_PAGEINDEX_BUILD_WITH_LLM", "0")
    monkeypatch.setattr("grid_agent_core.indexes.make_pageindex_llm", lambda _cfg: FakeLLM("{}"))
    monkeypatch.setattr(
        "grid_agent_core.rag_compat.official_pageindex.rag.OfficialPageIndexRAG._load_official_modules",
        lambda _self: SimpleNamespace(
            md_to_tree=fake_md_to_tree,
            utils=SimpleNamespace(),
            source="fake-official-pageindex",
        ),
    )
    artifact_dir = write_artifact_fixture(tmp_path)

    build_vector_index(
        artifact_dir,
        provider="sentence_transformers",
        chunk_strategy="fixed",
    )
    build_pageindex(artifact_dir)
    pageindex_meta = json.loads(
        (artifact_dir / "indexes" / "pageindex" / "index.json").read_text(encoding="utf-8")
    )
    repo = GridRetrievalRepository(artifact_dir)

    vector = repo.search("vector", "readiness evidence")
    pageindex = repo.search("pageindex", "queue management")

    assert vector[0].artifact_source == "vector"
    assert pageindex_meta["logic"] == "vector_pageindex_rag_eval.OfficialPageIndexRAG"
    assert pageindex[0].artifact_source == "pageindex"


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
                        float("readiness" in lowered or "evidence" in lowered),
                        float("queue" in lowered or "cndm" in lowered),
                        float("gate" in lowered),
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
