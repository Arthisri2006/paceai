"""Hybrid FAISS + BM25 retrieval with transparent score fusion."""

from __future__ import annotations

import time
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from functools import cached_property

from config import Settings, settings
from src.bm25_search import BM25Search
from src.reranker import ResultReranker
from src.vector_store import VectorStore
from src.utils import tokenize
from src.academic_query import parse_academic_query, matches_document, course_structure_excerpt, is_course_overview


class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        bm25: BM25Search,
        config: Settings = settings,
        reranker: ResultReranker | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.bm25 = bm25
        self.config = config
        self.reranker = reranker or ResultReranker(config)
        self._cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self._cache_lock = Lock()

    @cached_property
    def document_catalog(self) -> dict[str, dict]:
        if self.vector_store.index is None:
            self.vector_store.load()
        return {chunk["source_url"]: chunk for chunk in self.vector_store.records}

    def _academic_scope(self, question: str) -> set[str] | None:
        query = parse_academic_query(question)
        if not query.scoped:
            return None
        # Explicit regulation/branch constraints apply to academic document
        # queries, not ordinary department-specific placement questions.
        if not query.syllabus and not query.regulations:
            return None
        return {url for url, chunk in self.document_catalog.items()
                if matches_document(query, chunk)}

    def _intent_candidates(self, question: str) -> list[dict]:
        """Promote authoritative indexed routes for a few unambiguous campus intents."""

        terms = set(tokenize(question))
        academic = parse_academic_query(question)
        course_overview = is_course_overview(question)
        candidates: list[dict] = []
        for chunk in self.vector_store.records:
            url = chunk["source_url"].lower().rstrip("/")
            title = str(chunk.get("title") or "").lower()
            text = chunk["text"].lower()
            score = 0.0
            if course_overview:
                if url.endswith("/admissions/courses-offered"):
                    score = 1.0
            elif academic.syllabus:
                page = int(chunk.get("page") or 0)
                if (academic.overview and academic.scoped and matches_document(academic, chunk)
                        and 1 <= page <= 8 and "course structure" in text):
                    # Subject tables outrank induction-only pages.
                    score = 1.0 - (page - 1) * 0.005
                    if "semester" not in text:
                        score -= 0.15
            elif "department" in terms:
                if url == "https://pace.ac.in" or url.endswith("/admissions/courses-offered"):
                    score = 1.0
                elif "/academics/departments/" in url and chunk.get("position") == 0:
                    score = 0.8
            elif {"student", "service"}.issubset(terms):
                service_terms = (
                    "hostel", "nss", "ncc", "grievance", "welfare", "library", "skill"
                )
                if any(term in url or term in title for term in service_terms):
                    score = 0.9
                elif chunk.get("category") == "student_services":
                    score = 0.8
            elif {"question", "paper"}.issubset(terms):
                if "previous question papers" in text:
                    score = 1.0
            if score:
                candidates.append({"chunk": chunk, "intent_score": score})

        candidates.sort(key=lambda item: item["intent_score"], reverse=True)
        selected: list[dict] = []
        source_counts: dict[str, int] = {}
        for item in candidates:
            source = item["chunk"]["source_url"]
            if source_counts.get(source, 0) >= self.config.max_chunks_per_source:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1
            selected.append(item)
            if len(selected) >= self.config.bm25_top_k:
                break
        return selected

    def search(self, question: str, top_k: int | None = None) -> dict:
        """Cache retrieval only; exact case and punctuation retain query meaning.

        An instance belongs to one immutable loaded index snapshot. Restart after
        rebuilding indexes; TTL additionally bounds repeated-query retention.
        """
        if not isinstance(question, str) or not question.strip() or len(question) > 1500:
            raise ValueError("Ask a question between 1 and 1500 characters.")
        if top_k is not None and (not isinstance(top_k, int) or top_k < 1):
            raise ValueError("top_k must be a positive integer.")
        started = time.perf_counter()
        key = (question.strip(), top_k or self.config.final_top_k)
        enabled = self.config.retrieval_cache_size > 0 and self.config.retrieval_cache_ttl > 0
        if enabled:
            with self._cache_lock:
                now = time.monotonic()
                for stale in [k for k, (expiry, _) in self._cache.items() if expiry <= now]:
                    del self._cache[stale]
                if key in self._cache:
                    self._cache.move_to_end(key)
                    result = deepcopy(self._cache[key][1])
                    result["timing"].update(vector_seconds=0.0, bm25_seconds=0.0,
                                           rerank_seconds=0.0, cache_hit=True,
                                           retrieval_seconds=round(time.perf_counter() - started, 6))
                    return result
        result = self._search(question.strip(), top_k)
        result["timing"]["cache_hit"] = False
        if enabled:
            with self._cache_lock:
                self._cache[key] = (time.monotonic() + self.config.retrieval_cache_ttl, deepcopy(result))
                self._cache.move_to_end(key)
                while len(self._cache) > self.config.retrieval_cache_size:
                    self._cache.popitem(last=False)
        return result

    def _search(self, question: str, top_k: int | None = None) -> dict:
        started = time.perf_counter()
        allowed = self._academic_scope(question)
        if allowed == set():
            return {"results": [], "timing": {"retrieval_seconds": round(time.perf_counter() - started, 4),
                    "vector_seconds": 0.0, "bm25_seconds": 0.0, "rerank_seconds": 0.0}}
        academic = parse_academic_query(question)
        # Only an explicit, unambiguous document overview can skip inference.
        # Detailed subjects, missing scope, comparisons, and unparsed tables
        # continue through the normal hybrid retrieval path.
        if (academic.overview and len(academic.branches) == 1
                and len(academic.regulations) == 1 and allowed is not None
                and len(allowed) == 1):
            overview = self._overview_pages(allowed)
            if overview:
                results = [{**item, "vector_score": 0.0, "bm25_score": 0.0,
                            "reranker_score": 0.0, "final_score": 0.9 * item["intent_score"]}
                           for item in overview[:top_k or self.config.final_top_k]]
                return {"results": results, "timing": {
                    "vector_seconds": 0.0, "bm25_seconds": 0.0, "rerank_seconds": 0.0,
                    "retrieval_mode": "exact_syllabus",
                    "retrieval_seconds": round(time.perf_counter() - started, 4)}}
        vector_results = self.vector_store.search(question, self.config.vector_top_k, allowed)
        vector_elapsed = time.perf_counter() - started
        bm25_started = time.perf_counter()
        bm25_results = self.bm25.search(question, self.config.bm25_top_k, allowed)
        bm25_elapsed = time.perf_counter() - bm25_started

        merged: dict[str, dict] = {}
        for rank, item in enumerate(vector_results, start=1):
            chunk = item["chunk"]
            entry = merged.setdefault(
                chunk["id"], {"chunk": chunk, "vector_score": 0.0, "bm25_score": 0.0}
            )
            entry["vector_score"] = item["vector_score"]
            entry["vector_rank"] = rank
        for rank, item in enumerate(bm25_results, start=1):
            chunk = item["chunk"]
            entry = merged.setdefault(
                chunk["id"], {"chunk": chunk, "vector_score": 0.0, "bm25_score": 0.0}
            )
            entry["bm25_score"] = item["bm25_score"]
            entry["bm25_rank"] = rank
        for item in self._intent_candidates(question):
            chunk = item["chunk"]
            if allowed is not None and chunk["source_url"] not in allowed:
                continue
            entry = merged.setdefault(
                chunk["id"],
                {
                    "chunk": chunk,
                    "vector_score": 0.0,
                    "bm25_score": 0.0,
                    "intent_score": 0.0,
                },
            )
            entry["intent_score"] = max(
                entry.get("intent_score", 0.0), item["intent_score"]
            )

        maximum_bm25 = max((item["bm25_score"] for item in merged.values()), default=1.0) or 1.0
        for item in merged.values():
            # Inner-product similarity for normalized vectors lies in [-1, 1].
            vector_normalized = (
                max(0.0, min(1.0, (item["vector_score"] + 1.0) / 2.0))
                if "vector_rank" in item
                else 0.0
            )
            bm25_normalized = (
                max(0.0, item["bm25_score"] / maximum_bm25)
                if "bm25_rank" in item
                else 0.0
            )
            item["final_score"] = (
                self.config.vector_weight * vector_normalized
                + self.config.bm25_weight * bm25_normalized
            )

        rerank_started = time.perf_counter()
        ranked = self.reranker.rerank(question, list(merged.values()))
        rerank_elapsed = time.perf_counter() - rerank_started
        count = top_k or self.config.final_top_k
        diversified: list[dict] = []
        source_counts: dict[str, int] = {}
        for item in ranked:
            source = item["chunk"]["source_url"]
            if source_counts.get(source, 0) >= self.config.max_chunks_per_source:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1
            diversified.append(item)
            if len(diversified) >= count:
                break
        return {
            "results": diversified,
            "timing": {
                "vector_seconds": round(vector_elapsed, 4),
                "bm25_seconds": round(bm25_elapsed, 4),
                "rerank_seconds": round(rerank_elapsed, 4),
                "retrieval_seconds": round(time.perf_counter() - started, 4),
            },
        }

    def _overview_pages(self, allowed: set[str]) -> list[dict]:
        """Join parsed rows by source page, not arbitrary chunk boundaries.

        This is used only by the explicit single-document direct-answer path;
        it neither enlarges LLM context nor embeds combined oversized pages.
        """
        pages = {}
        for chunk in self.vector_store.records:
            page = int(chunk.get("page") or 0)
            if (chunk["source_url"] not in allowed or chunk.get("document_type") != "pdf"
                    or not 1 <= page <= 8 or "course structure" not in chunk["text"].lower()):
                continue
            sections = course_structure_excerpt(chunk["text"])
            if not sections:
                continue
            key = (chunk["source_url"], page)
            item = pages.setdefault(key, {"chunk": chunk, "intent_score": 1.0 - (page - 1) * .005,
                                          "overview_sections": {}})
            for heading, subjects in sections:
                merged = item["overview_sections"].setdefault(heading, [])
                merged.extend(subject for subject in subjects if subject not in merged)
        return sorted(pages.values(), key=lambda x: x["chunk"]["page"])[:self.config.max_chunks_per_source]
