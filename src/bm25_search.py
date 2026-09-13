"""Persistent exact-keyword search using BM25."""

from __future__ import annotations

import numpy as np
from rank_bm25 import BM25Okapi

from config import Settings, settings
from src.utils import load_json, save_json, tokenize


class BM25Search:
    CORPUS_FILE = "bm25_corpus.json"

    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.chunks: list[dict] = []
        self.corpus: list[list[str]] = []
        self.index: BM25Okapi | None = None

    @staticmethod
    def _searchable_text(chunk: dict) -> str:
        # Repetition is a simple BM25 field boost: exact titles and departments
        # should outweigh an incidental keyword buried in a long PDF page.
        title = str(chunk.get("title") or "")
        section = str(chunk.get("section") or "")
        department = str(chunk.get("department") or "")
        category = str(chunk.get("category") or "")
        source_url = str(chunk.get("source_url") or "")
        return " ".join(
            [title] * 4
            + [section] * 2
            + [department] * 3
            + [category] * 3
            + [source_url] * 4
            + [str(chunk.get("document_type") or ""), chunk["text"]]
        )

    def build(self, chunks: list[dict]) -> None:
        if not chunks:
            raise ValueError("Cannot build BM25 without chunks.")
        self.chunks = chunks
        self.corpus = [tokenize(self._searchable_text(chunk)) for chunk in chunks]
        self.index = BM25Okapi(self.corpus)
        save_json(
            self.config.index_dir / self.CORPUS_FILE,
            {"tokens": self.corpus, "chunks": chunks},
        )

    def load(self) -> None:
        payload = load_json(self.config.index_dir / self.CORPUS_FILE)
        if not payload:
            raise FileNotFoundError("BM25 index is missing. Run: python build_index.py")
        self.corpus = payload["tokens"]
        self.chunks = payload["chunks"]
        self.index = BM25Okapi(self.corpus)

    def search(self, question: str, top_k: int, allowed_sources: set[str] | None = None) -> list[dict]:
        if self.index is None:
            self.load()
        if not self.chunks:
            return []
        scores = self.index.get_scores(tokenize(question))
        results: list[dict] = []
        source_counts: dict[str, int] = {}
        for index in np.argsort(scores)[::-1]:
            if scores[index] <= 0:
                break
            chunk = self.chunks[int(index)]
            source = chunk["source_url"]
            if allowed_sources is not None and source not in allowed_sources:
                continue
            if source_counts.get(source, 0) >= self.config.max_chunks_per_source:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1
            results.append({"chunk": chunk, "bm25_score": float(scores[index])})
            if len(results) >= top_k:
                break
        return results
