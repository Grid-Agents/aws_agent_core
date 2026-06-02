from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from .worker_lib import load_corpus, run_worker

LLM_MODEL = os.getenv("GRID_GRAPHRAG_MODEL", "claude-haiku-4-5")
LLM_BASE_URL = "https://api.anthropic.com/v1"
EMBED_MODEL = os.getenv("GRID_GRAPHRAG_EMBED_MODEL", "voyage-law-2")


def _build_cache_config(cache_dir: str) -> Any:
    from graphrag.config.models.cache_config import CacheConfig

    return CacheConfig(type="file", base_dir=cache_dir)


def _build_config(graph_dir: str) -> Any:
    from graphrag.config.enums import ModelType, StorageType, VectorStoreType
    from graphrag.config.models.graph_rag_config import GraphRagConfig
    from graphrag.config.models.language_model_config import LanguageModelConfig
    from graphrag.config.models.reporting_config import ReportingConfig
    from graphrag.config.models.storage_config import StorageConfig
    from graphrag.config.models.text_embedding_config import TextEmbeddingConfig
    from graphrag.config.models.vector_store_config import VectorStoreConfig

    graph_root = Path(graph_dir).resolve()
    graph_root.mkdir(parents=True, exist_ok=True)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    if not anthropic_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required to build the local GraphRAG index.")
    if not voyage_key:
        raise RuntimeError("VOYAGE_API_KEY is required to build the local GraphRAG index.")

    llm_model = LanguageModelConfig(
        type=ModelType.Chat,
        model_provider="anthropic",
        model=LLM_MODEL,
        api_key=anthropic_key,
        api_base=LLM_BASE_URL,
        max_tokens=1200,
        temperature=0,
    )
    embed_model = LanguageModelConfig(
        type=ModelType.Embedding,
        model_provider="voyage",
        model=EMBED_MODEL,
        api_key=voyage_key,
    )
    return GraphRagConfig(
        root_dir=str(graph_root),
        models={
            "default_chat_model": llm_model,
            "default_embedding_model": embed_model,
        },
        output=StorageConfig(
            type=StorageType.file,
            base_dir=str(graph_root / "output"),
        ),
        cache=_build_cache_config(str(graph_root / "cache")),
        reporting=ReportingConfig(type="file", base_dir=str(graph_root / "logs")),
        vector_store={
            "default_vector_store": VectorStoreConfig(
                type=VectorStoreType.LanceDB,
                db_uri=str(graph_root / "lancedb"),
            )
        },
        embed_text=TextEmbeddingConfig(names=["entity.description", "text_unit.text"]),
    )


def index_fn(request: dict[str, Any]) -> dict[str, Any]:
    import importlib.metadata

    import graphrag.api as graph_api
    import pandas as pd

    corpus = load_corpus(request["corpus_path"])
    graph_dir = Path(request["graph_dir"])
    graph_dir.mkdir(parents=True, exist_ok=True)
    config = _build_config(str(graph_dir))
    input_documents = pd.DataFrame(
        [
            {
                "id": document_id,
                "title": document_id,
                "text": text,
                "creation_date": "",
            }
            for document_id, text in corpus.items()
        ]
    )
    results = asyncio.run(
        graph_api.build_index(
            config=config,
            input_documents=input_documents,
            verbose=False,
        )
    )
    errors = [result for result in results if result.error is not None]
    if errors:
        raise RuntimeError(
            "GraphRAG pipeline errors: "
            + "; ".join(f"{result.workflow}: {result.error}" for result in errors)
        )
    output_dir = graph_dir / "output"
    stats = _read_graph_stats(output_dir)
    try:
        stats["package_version"] = importlib.metadata.version("graphrag")
    except importlib.metadata.PackageNotFoundError:
        stats["package_version"] = "unknown"
    return {"graph_stats": stats}


def query_fn(request: dict[str, Any]) -> dict[str, Any]:
    import graphrag.api as graph_api
    import pandas as pd

    graph_dir = Path(request["graph_dir"])
    output_dir = graph_dir / "output"
    config = _build_config(str(graph_dir))

    def load_table(name: str) -> pd.DataFrame:
        path = output_dir / f"{name}.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    covariates = None
    covariates_path = output_dir / "covariates.parquet"
    if covariates_path.exists():
        try:
            covariates = pd.read_parquet(covariates_path)
        except Exception:
            covariates = None

    _response, context_data = asyncio.run(
        graph_api.local_search(
            config=config,
            entities=load_table("entities"),
            communities=load_table("communities"),
            community_reports=load_table("community_reports"),
            text_units=load_table("text_units"),
            relationships=load_table("relationships"),
            covariates=covariates,
            community_level=2,
            response_type="single sentence",
            query=str(request["query"]),
        )
    )
    contexts = _extract_contexts(
        context_data,
        load_table("text_units"),
        int(request.get("top_k", 10)),
    )
    return {"contexts": contexts}


def _read_graph_stats(output_dir: Path) -> dict[str, Any]:
    import pandas as pd

    stats: dict[str, Any] = {}
    for name, parquet_file in [
        ("text_units", "text_units.parquet"),
        ("entities", "entities.parquet"),
        ("communities", "communities.parquet"),
        ("community_reports", "community_reports.parquet"),
        ("relationships", "relationships.parquet"),
    ]:
        path = output_dir / parquet_file
        if not path.exists():
            stats[name] = 0
            continue
        try:
            stats[name] = len(pd.read_parquet(path))
        except Exception:
            stats[name] = -1
    return stats


def _extract_contexts(context_data: dict[str, Any], text_units_df: Any, top_k: int) -> list[dict[str, Any]]:
    sources = context_data.get("sources") if isinstance(context_data, dict) else None
    if sources is None or getattr(sources, "empty", False):
        return []

    short_id_to_doc: dict[str, str] = {}
    text_to_doc: dict[str, str] = {}
    if not text_units_df.empty and "document_id" in text_units_df.columns:
        valid = text_units_df[text_units_df["document_id"].astype(str) != ""]
        document_ids = valid["document_id"].astype(str)
        if "human_readable_id" in valid.columns:
            short_id_to_doc = {
                str(short_id): document_id
                for short_id, document_id in zip(valid["human_readable_id"], document_ids)
                if str(short_id)
            }
        if "text" in valid.columns:
            text_to_doc = {
                str(text): document_id
                for text, document_id in zip(valid["text"], document_ids)
                if str(text)
            }

    contexts: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for rank, (_, row) in enumerate(sources.iterrows()):
        if len(contexts) >= top_k:
            break
        text = str(row.get("text", "")).strip()
        if not text or text in seen_texts:
            continue
        document_id = short_id_to_doc.get(str(row.get("id", ""))) or text_to_doc.get(text)
        if not document_id:
            continue
        seen_texts.add(text)
        contexts.append(
            {
                "document_id": document_id,
                "text": text,
                "score": float(1.0 / (rank + 1)),
            }
        )
    return contexts


if __name__ == "__main__":
    run_worker(index_fn, query_fn)
