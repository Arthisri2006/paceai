"""Persistent FAISS cosine-similarity index."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import faiss
import numpy as np

from config import Settings, settings
from src.utils import load_json, save_json
from src.embedding_text import embedding_text


class Embedder(Protocol):
    def encode_documents(self, texts: list[str]) -> np.ndarray: ...
    def encode_query(self, question: str) -> np.ndarray: ...


class VectorStore:
    INDEX_FILE = "vectors.faiss"
    RECORDS_FILE = "vector_records.json"

    def __init__(self, embedder: Embedder, config: Settings = settings) -> None:
        self.embedder = embedder
        self.config = config
        self.index: faiss.Index | None = None
        self.records: list[dict] = []

    @staticmethod
    def _searchable_text(chunk: dict) -> str:
        return embedding_text(chunk)

    def build(self, chunks: list[dict]) -> None:
        if not chunks:
            raise ValueError("Cannot build a vector index without chunks.")
        vectors = self.embedder.encode_documents(
            [self._searchable_text(chunk) for chunk in chunks]
        )
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise ValueError("Embedding count does not match chunk count.")
        vectors = np.ascontiguousarray(vectors, dtype="float32")
        faiss.normalize_L2(vectors)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)
        self.records = chunks
        self.save()

    def save(self) -> None:
        if self.index is None:
            raise RuntimeError("No FAISS index has been built.")
        self.config.index_dir.mkdir(parents=True, exist_ok=True)
        index_path = self.config.index_dir / self.INDEX_FILE
        temporary = Path(str(index_path) + ".tmp")
        faiss.write_index(self.index, str(temporary))
        temporary.replace(index_path)
        save_json(self.config.index_dir / self.RECORDS_FILE, self.records)

    def load(self) -> None:
        index_path = self.config.index_dir / self.INDEX_FILE
        records_path = self.config.index_dir / self.RECORDS_FILE
        if not index_path.exists() or not records_path.exists():
            raise FileNotFoundError("Vector index is missing. Run: python build_index.py")
        self.index = faiss.read_index(str(index_path))
        self.records = load_json(records_path, [])
        if self.index.ntotal != len(self.records):
            raise ValueError("FAISS index and metadata count do not match.")

    def search(self, question: str, top_k: int, allowed_sources: set[str] | None = None) -> list[dict]:
        if self.index is None:
            self.load()
        if not self.records:
            return []
        query = np.ascontiguousarray(self.embedder.encode_query(question)[None, :], dtype="float32")
        faiss.normalize_L2(query)
        # Filter before top-k selection; filtering an already truncated global
        # shortlist can lose every matching page of the requested regulation.
        count = len(self.records) if allowed_sources is not None else min(top_k, len(self.records))
        scores, indices = self.index.search(query, count)
        results: list[dict] = []
        for score, index in zip(scores[0], indices[0], strict=True):
            if index < 0:
                continue
            chunk = self.records[int(index)]
            if allowed_sources is not None and chunk["source_url"] not in allowed_sources:
                continue
            results.append({"chunk": chunk, "vector_score": float(score)})
            if len(results) >= top_k:
                break
        return results
