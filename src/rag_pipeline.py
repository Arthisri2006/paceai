"""Grounded RAG orchestration with enforced citations and timings."""

from __future__ import annotations

import time
import json
import re
from contextlib import closing
from collections.abc import Iterator

from config import Settings, settings
from src.llm import BaseLLM
from src.retriever import HybridRetriever
from src.academic_query import parse_academic_query, course_structure_excerpt, is_course_overview
from src.answer_policy import (NOT_FOUND, conversational_reply, guarded_text, AnswerQualityError)




def has_sufficient_evidence(item: dict, config: Settings = settings) -> bool:
    """Return True only when a retrieved chunk has meaningful PACE evidence."""
    return item["final_score"] >= config.min_retrieval_score and (
        item.get("vector_score", 0.0) >= config.min_vector_evidence
        or item.get("reranker_score", 0.0) >= config.min_lexical_evidence
        or item.get("intent_score", 0.0) >= 0.8
    )


class RagPipeline:
    def __init__(
        self, retriever: HybridRetriever, llm: BaseLLM, config: Settings = settings
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.config = config

    def _prepare(self, question: str) -> tuple[dict, list[dict], str | None]:
        retrieval = self.retriever.search(question)
        results = [
            item
            for item in retrieval["results"]
            if has_sufficient_evidence(item, self.config)
        ]
        # When an unambiguous campus intent matched an authoritative indexed
        # route, exclude merely similar pages from the generation context.
        intent_results = [
            item for item in results if item.get("intent_score", 0.0) >= 0.8
        ]
        if intent_results:
            results = intent_results
        if not results:
            return retrieval, [], None

        context_parts: list[str] = []
        used_results: list[dict] = []
        used_words = 0
        labels: dict[tuple, int] = {}
        for item in results[: self.config.max_context_sources]:
            chunk = item["chunk"]
            source_key = (chunk["source_url"], chunk.get("page"))
            source_number = labels.setdefault(source_key, len(labels) + 1)
            available = self.config.max_context_words - used_words
            if available <= 0:
                break
            words = chunk["text"].split()
            excerpt = chunk["text"] if len(words) <= available else " ".join(words[:available])
            used_words += len(excerpt.split())
            context_parts.append(
                json.dumps({"source": f"[S{source_number}]", "title": chunk["title"],
                            "page": chunk.get("page"), "excerpt": excerpt}, ensure_ascii=False)
            )
            used_results.append(item)
        joined_context = "\n\n".join(context_parts)
        prompt = (
            f"Question: {json.dumps(question.strip(), ensure_ascii=False)}\n\n"
            f"Context:\n{joined_context}"
        )
        return retrieval, used_results, prompt

    @staticmethod
    def _sources(results: list[dict]) -> list[dict]:
        sources: list[dict] = []
        seen: set[tuple[str, int | None]] = set()
        for item in results:
            chunk = item["chunk"]
            key = (chunk["source_url"], chunk.get("page"))
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "title": chunk["title"],
                    "url": chunk["source_url"],
                    "page": chunk.get("page"),
                    "document_type": chunk["document_type"],
                }
            )
        return sources

    @staticmethod
    def _direct_answer(question: str, results: list[dict]) -> str | None:
        """Use deterministic wording for exact document-navigation intents."""
        if not results:
            return None
        if is_course_overview(question):
            if any(
                item["chunk"]["source_url"].rstrip("/").endswith(
                    "/admissions/courses-offered"
                )
                for item in results
            ):
                return (
                    "The official PACE Courses Offered page is linked below. "
                    "Open it for the published programme details."
                )
        if parse_academic_query(question).overview and any(
            item.get("intent_score", 0.0) >= 0.8
            and item["chunk"].get("document_type") == "pdf"
            for item in results
        ):
            title = str(results[0]["chunk"]["title"]).replace("_", " ")
            lines = [f"Here is an excerpt from the official {title} syllabus:"]
            labels: dict[tuple, int] = {}
            for item in results:
                key = (item["chunk"]["source_url"], item["chunk"].get("page"))
                number = labels.setdefault(key, len(labels) + 1)
                sections = item.get("overview_sections")
                for heading, subjects in (sections.items() if sections else course_structure_excerpt(item["chunk"]["text"])):
                    lines.append(f"\n**{heading} [S{number}]**\n" + "; ".join(subjects) + ".")
            if len(lines) == 1:
                return f"The official {title} syllabus is available in the cited PACE PDF. Open it for the complete course structure and subject details."
            lines.append("\nThis is a partial overview of the cited pages. Open the official PDF for all semesters, credits, electives, and detailed units.")
            return "\n".join(lines)
        return None

    @staticmethod
    def format_sources(sources: list[dict]) -> str:
        if not sources:
            return ""
        lines = ["\n\nSources:"]
        for number, source in enumerate(sources, start=1):
            page = f" (page {source['page']})" if source.get("page") else ""
            lines.append(f"[S{number}] {source['title']}{page} - {source['url']}")
        return "\n".join(lines)

    def ask(self, question: str) -> dict:
        answer = ""
        completed = None
        for event in self.stream(question):
            if event["type"] == "token":
                answer += event["text"]
            elif event["type"] == "replace":
                answer = event["text"]
            elif event["type"] == "complete":
                completed = event
        if completed is None:
            raise RuntimeError("Answer stream did not complete")
        return {"answer": answer, "sources": completed["sources"],
                "retrieved": completed["retrieved"], "timing": completed["timing"]}

    def stream(self, question: str) -> Iterator[dict]:
        if not isinstance(question, str) or not question.strip() or len(question) > 1500:
            raise ValueError("Ask a question between 1 and 1500 characters.")
        total_started = time.perf_counter()
        greeting = conversational_reply(question)
        if greeting is not None:
            yield {"type": "token", "text": greeting}
            yield {"type": "complete", "sources": [], "retrieved": [],
                   "timing": {"retrieval_seconds": 0.0, "llm_seconds": 0.0,
                              "answer_mode": "conversation",
                              "total_seconds": round(time.perf_counter() - total_started, 4)}}
            return
        retrieval, results, prompt = self._prepare(question)
        sources = self._sources(results)
        if prompt is None:
            yield {"type": "token", "text": NOT_FOUND}
            yield {
                "type": "complete",
                "sources": [],
                "retrieved": retrieval["results"],
                "timing": {
                    **retrieval["timing"],
                    "llm_seconds": 0.0,
                    "answer_mode": "not_found",
                    "total_seconds": round(time.perf_counter() - total_started, 4),
                },
            }
            return

        direct_answer = self._direct_answer(question, results)
        if direct_answer is not None:
            yield {"type": "token", "text": direct_answer}
            yield {"type": "token", "text": self.format_sources(sources)}
            yield {
                "type": "complete",
                "sources": sources,
                "retrieved": retrieval["results"],
                "timing": {
                    **retrieval["timing"],
                    "llm_seconds": 0.0,
                    "answer_mode": "direct",
                    "total_seconds": round(time.perf_counter() - total_started, 4),
                },
            }
            return

        llm_started = time.perf_counter()
        generated = ""
        mode = "gemini" if self.config.llm_provider.lower() == "gemini" else "local_llm"
        usage: dict = {}
        try:
            with closing(guarded_text(self.llm.stream_with_usage(prompt, usage))) as tokens:
                for token in tokens:
                    generated += token
                    if NOT_FOUND.lower() in generated.lower():
                        mode = "not_found"
                        sources = []
                        yield {"type": "replace", "text": NOT_FOUND}
                        break
                    yield {"type": "token", "text": token}
            if mode != "not_found":
                citations = [int(value) for value in re.findall(r"\bS(\d+)\b", generated)]
                if not citations or any(number < 1 or number > len(sources) for number in citations):
                    raise AnswerQualityError("Missing or unknown source label")
        except AnswerQualityError:
            mode = "quality_fallback"
            sources = []
            yield {"type": "replace", "text": "I couldn't produce a reliable answer from these excerpts. Please ask for a specific subject or semester, or rephrase your question."}
        yield {"type": "token", "text": self.format_sources(sources)}
        yield {
            "type": "complete",
            "sources": sources,
            "retrieved": retrieval["results"],
            "timing": {
                **retrieval["timing"],
                "llm_seconds": round(time.perf_counter() - llm_started, 4),
                "answer_mode": mode,
                "usage": usage,
                "total_seconds": round(time.perf_counter() - total_started, 4),
            },
        }
