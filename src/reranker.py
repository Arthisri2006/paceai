"""Fast default reranking plus an optional cross-encoder."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

from config import Settings, settings
from src.utils import tokenize


class ResultReranker:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @cached_property
    def cross_encoder(self) -> CrossEncoder:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(
            self.config.reranker_model,
            cache_folder=str(self.config.cache_dir / "models"),
        )

    @staticmethod
    def _lexical_score(question: str, chunk: dict) -> float:
        query_terms = set(tokenize(question))
        if not query_terms:
            return 0.0
        title = str(chunk.get("title") or "")
        metadata = " ".join(
            str(chunk.get(field) or "")
            for field in ("title", "section", "department", "category", "source_url")
        )
        searchable = f"{metadata} {chunk.get('text', '')}"
        title_terms = set(tokenize(title))
        metadata_terms = set(tokenize(metadata))
        document_terms = set(tokenize(searchable))
        title_overlap = query_terms & title_terms
        metadata_overlap = query_terms & metadata_terms
        title_coverage = len(title_overlap) / len(query_terms)
        title_precision = len(title_overlap) / max(1, len(title_terms))
        metadata_coverage = len(metadata_overlap) / len(query_terms)
        document_coverage = len(query_terms & document_terms) / len(query_terms)
        exact_bonus = 0.1 if question.lower() in searchable.lower() else 0.0
        complete_match_bonus = 0.1 if query_terms.issubset(document_terms) else 0.0
        score = (
            0.4 * title_coverage
            + 0.25 * title_precision
            + 0.2 * metadata_coverage
            + 0.15 * document_coverage
            + exact_bonus
            + complete_match_bonus
        )
        return min(1.0, score)

    def rerank(self, question: str, results: list[dict]) -> list[dict]:
        if not results:
            return []
        if self.config.use_cross_encoder:
            pairs = [(question, result["chunk"]["text"]) for result in results]
            raw_scores = self.cross_encoder.predict(pairs)
            low, high = float(min(raw_scores)), float(max(raw_scores))
            span = high - low or 1.0
            for result, raw in zip(results, raw_scores, strict=True):
                cross_score = (float(raw) - low) / span
                result["reranker_score"] = cross_score
                result["final_score"] = 0.65 * result["final_score"] + 0.35 * cross_score
        else:
            for result in results:
                lexical = self._lexical_score(question, result["chunk"])
                result["reranker_score"] = lexical
                result["final_score"] = 0.85 * result["final_score"] + 0.15 * lexical
        for result in results:
            intent = result.get("intent_score", 0.0)
            if intent:
                intent_floor = 0.9 * intent + 0.1 * result.get("reranker_score", 0.0)
                result["final_score"] = max(result["final_score"], intent_floor)
        return sorted(results, key=lambda item: item["final_score"], reverse=True)
