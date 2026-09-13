from __future__ import annotations

from dataclasses import replace

from config import settings
from src.llm import BaseLLM
from src.rag_pipeline import NOT_FOUND, RagPipeline


class FakeLLM(BaseLLM):
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, prompt: str):
        self.calls += 1
        assert "Context:" in prompt
        yield "PACE provides placement training [S1]."


class FakeRetriever:
    def __init__(self, results: list[dict]) -> None:
        self.results = results

    def search(self, question: str) -> dict:
        return {
            "results": self.results,
            "timing": {"retrieval_seconds": 0.001},
        }


def _result(score: float = 0.9) -> dict:
    return {
        "final_score": score,
        "vector_score": 0.8,
        "bm25_score": 2.0,
        "chunk": {
            "id": "placement-1",
            "text": "The placement cell provides aptitude and interview training.",
            "title": "Training and Placements",
            "section": "Placement Services",
            "source_url": "https://pace.ac.in/training-placements",
            "document_type": "webpage",
            "department": None,
            "page": None,
            "category": "placements",
        },
    }


def test_rag_enforces_sources_and_timing() -> None:
    llm = FakeLLM()
    response = RagPipeline(FakeRetriever([_result()]), llm).ask(
        "What placement services are offered?"
    )

    assert llm.calls == 1
    assert "https://pace.ac.in/training-placements" in response["answer"]
    assert response["sources"][0]["title"] == "Training and Placements"
    assert "total_seconds" in response["timing"]


def test_rag_skips_llm_when_evidence_is_too_weak() -> None:
    llm = FakeLLM()
    configured = replace(settings, min_retrieval_score=0.5)
    response = RagPipeline(FakeRetriever([_result(0.1)]), llm, configured).ask(
        "Who won an unrelated football match?"
    )

    assert llm.calls == 0
    assert response["answer"] == NOT_FOUND
    assert response["timing"]["llm_seconds"] == 0.0


def test_rag_prefers_authoritative_intent_results_over_similar_pages() -> None:
    llm = FakeLLM()
    authoritative = {**_result(), "intent_score": 1.0}
    similar = {
        **_result(),
        "chunk": {
            **_result()["chunk"],
            "id": "similar-1",
            "title": "Similar page",
            "source_url": "https://pace.ac.in/similar",
        },
    }
    response = RagPipeline(FakeRetriever([authoritative, similar]), llm).ask(
        "What courses are offered?"
    )

    assert len(response["sources"]) == 1
    assert response["sources"][0]["url"] == authoritative["chunk"]["source_url"]


def test_exact_courses_navigation_uses_grounded_direct_answer() -> None:
    llm = FakeLLM()
    official = {
        **_result(),
        "intent_score": 1.0,
        "chunk": {
            **_result()["chunk"],
            "title": "courses",
            "source_url": "https://pace.ac.in/admissions/courses-offered",
        },
    }
    response = RagPipeline(FakeRetriever([official]), llm).ask(
        "What courses are offered at PACE?"
    )

    assert llm.calls == 0
    assert "Courses Offered" in response["answer"]
    assert "Diploma" not in response["answer"]  # Not supported by this fixture.
    assert response["timing"]["answer_mode"] == "direct"
