"""Cached construction of production backend resources."""

from __future__ import annotations

from functools import lru_cache
from dataclasses import replace
from pathlib import Path

from config import settings
from src.bm25_search import BM25Search
from src.embeddings import EmbeddingModel
from src.llm import create_llm
from src.rag_pipeline import RagPipeline
from src.reranker import ResultReranker
from src.retriever import HybridRetriever
from src.utils import load_json
from src.vector_store import VectorStore
from src.index_selection import selection, verify_selection


def load_pipeline() -> RagPipeline:
    return _load_pipeline(selection(settings))


@lru_cache(maxsize=1)
def _load_pipeline(selected: tuple) -> RagPipeline:
    """Load indexes once; models remain lazy and are then cached on first use."""

    verify_selection(selected)
    config = replace(settings, index_dir=Path(selected[0]))
    embedder = EmbeddingModel(config)
    vector_store = VectorStore(embedder, config)
    vector_store.load()
    bm25 = BM25Search(config)
    bm25.load()
    validate_indexes(vector_store, bm25, load_json(config.index_dir / "status.json", {}), config.embedding_model)
    # The persisted BM25 payload contains a second copy of the same records.
    # Once equality is checked, share metadata rather than retaining both copies.
    bm25.chunks = vector_store.records
    retriever = HybridRetriever(
        vector_store, bm25, config, ResultReranker(config)
    )
    return RagPipeline(retriever, create_llm(config), config)


def validate_indexes(vector_store, bm25, status: dict, embedding_model: str) -> None:
    if status.get("embedding_model") != embedding_model:
        raise ValueError("The saved embedding model does not match configuration. Rebuild the index before starting PACE AI.")
    if vector_store.records != bm25.chunks or len(bm25.corpus) != len(bm25.chunks):
        raise ValueError("Search indexes are inconsistent. Rebuild the index before starting PACE AI.")


def knowledge_base_status() -> dict:
    return load_json(
        Path(selection(settings)[0]) / "status.json",
        {"ready": False, "message": "Run: python build_index.py"},
    )
