from __future__ import annotations

from dataclasses import replace

import numpy as np

from config import settings
from src.bm25_search import BM25Search
from src.retriever import HybridRetriever
from src.vector_store import VectorStore


class FakeEmbedder:
    vocabulary = ("hostel", "r23", "placement")

    def _one(self, text: str) -> np.ndarray:
        lowered = text.lower()
        vector = np.array([lowered.count(term) for term in self.vocabulary], dtype="float32")
        if not vector.any():
            vector[:] = 0.01
        return vector

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._one(text) for text in texts])

    def encode_query(self, question: str) -> np.ndarray:
        return self._one(question)


def _chunk(identifier: str, text: str, category: str) -> dict:
    return {
        "id": identifier,
        "text": text,
        "title": category.title(),
        "section": category.title(),
        "source_url": f"https://pace.ac.in/{category}",
        "document_type": "webpage",
        "department": None,
        "page": None,
        "category": category,
        "position": 0,
    }


def test_hybrid_retrieval_persists_and_ranks_exact_terms(tmp_path) -> None:
    configured = replace(settings, index_dir=tmp_path, final_top_k=2)
    chunks = [
        _chunk("hostel", "Separate hostel facilities and dining are available.", "campus"),
        {
            **_chunk("r23", "Semester subjects and credits are published here.", "academics"),
            "title": "CSE R23 Syllabus",
            "department": "Computer Science and Engineering",
        },
        _chunk("placement", "Placement training includes aptitude and interviews.", "placements"),
    ]
    vector_store = VectorStore(FakeEmbedder(), configured)
    vector_store.build(chunks)
    bm25 = BM25Search(configured)
    bm25.build(chunks)

    fresh_vector_store = VectorStore(FakeEmbedder(), configured)
    fresh_bm25 = BM25Search(configured)
    response = HybridRetriever(fresh_vector_store, fresh_bm25, configured).search(
        "Where is the CSE R23 syllabus?"
    )

    assert response["results"][0]["chunk"]["id"] == "r23"
    assert response["results"][0]["bm25_score"] > 0
    assert response["results"][0]["vector_score"] > 0
    assert response["timing"]["retrieval_seconds"] >= 0


def test_bm25_only_result_gets_no_fake_vector_credit(tmp_path) -> None:
    configured = replace(
        settings,
        index_dir=tmp_path,
        vector_top_k=1,
        bm25_top_k=2,
        final_top_k=2,
    )
    chunks = [
        _chunk("hostel", "Hostel accommodation is described here.", "campus"),
        _chunk("rare", "zxqv exact keyword appears only here.", "general"),
        _chunk("placement", "Placement interview preparation is described here.", "placements"),
    ]
    vector_store = VectorStore(FakeEmbedder(), configured)
    vector_store.build(chunks)
    bm25 = BM25Search(configured)
    bm25.build(chunks)
    results = HybridRetriever(vector_store, bm25, configured).search("hostel zxqv")["results"]
    rare = next(item for item in results if item["chunk"]["id"] == "rare")

    assert "vector_rank" not in rare
    assert rare["vector_score"] == 0.0


def test_intent_layer_promotes_official_courses_route(tmp_path) -> None:
    configured = replace(settings, index_dir=tmp_path, final_top_k=2)
    chunks = [
        _chunk("generic", "PACE has many courses offered to students.", "general"),
        {
            **_chunk("courses", "Diploma and undergraduate programme table.", "admissions"),
            "title": "courses",
            "source_url": "https://pace.ac.in/admissions/courses-offered",
        },
        _chunk("placement", "Placement training information.", "placements"),
    ]
    vector_store = VectorStore(FakeEmbedder(), configured)
    vector_store.build(chunks)
    bm25 = BM25Search(configured)
    bm25.build(chunks)

    results = HybridRetriever(vector_store, bm25, configured).search(
        "What courses are offered at PACE?"
    )["results"]

    assert results[0]["chunk"]["id"] == "courses"
    assert results[0]["intent_score"] == 1.0


def test_generic_syllabus_intent_prefers_course_structure_pages(tmp_path) -> None:
    configured = replace(settings, index_dir=tmp_path, final_top_k=2)
    chunks = [
        {
            **_chunk("overview", "R23 undergraduate course structure.", "academics"),
            "title": "CSE_R23",
            "source_url": "https://pace.ac.in/syllabus/CSE_R23.pdf",
            "document_type": "pdf",
            "page": 1,
        },
        {
            **_chunk("late", "RSA Algorithm and security lab exercise.", "academics"),
            "title": "CSE_R23",
            "source_url": "https://pace.ac.in/syllabus/CSE_R23.pdf",
            "document_type": "pdf",
            "page": 125,
        },
    ]
    vector_store = VectorStore(FakeEmbedder(), configured)
    vector_store.build(chunks)
    bm25 = BM25Search(configured)
    bm25.build(chunks)

    results = HybridRetriever(vector_store, bm25, configured).search(
        "What is the CSE R23 syllabus?"
    )["results"]

    assert results[0]["chunk"]["id"] == "overview"
    assert results[0]["intent_score"] >= 0.8
