from dataclasses import replace

import pytest

from config import settings
from src.academic_query import parse_academic_query, matches_document, course_structure_excerpt
from src.bm25_search import BM25Search
from src.vector_store import VectorStore
from src.retriever import HybridRetriever
from src.rag_pipeline import RagPipeline
from tests.test_retrieval import FakeEmbedder, _chunk
from tests.test_rag import FakeLLM


@pytest.mark.parametrize("question", [
    "tell me the syllabus of aiml in r23 regulation",
    "Please give me the AI & ML syllabus under R-23 regulations",
    "Show the curriculum for Artificial Intelligence and Machine Learning R23",
])
def test_screenshot_and_paraphrases_identify_same_document(question):
    query = parse_academic_query(question)
    assert query.branches == {"AIML"}
    assert query.regulations == {"r23"}
    assert query.overview
    base = {"title": "AIML_R23", "source_url": "https://pace.ac.in/syllabus/AIML_R23.pdf", "document_type": "pdf"}
    assert matches_document(query, base)
    for title in ("AIML_R21", "AIDS_R23", "CSE_R23", "CSE_IOT_R23"):
        assert not matches_document(query, {**base, "title": title, "source_url": f"https://pace.ac.in/syllabus/{title}.pdf"})


def test_subject_question_does_not_get_generic_overview():
    query = parse_academic_query("Explain machine learning unit 2 in AIML R23 syllabus")
    assert query.branches == {"AIML"}
    assert not query.overview


def test_cse_does_not_match_iot_specialization():
    assert not matches_document(parse_academic_query("CSE R23 syllabus"),
        {"title": "CSE_IOT_R23", "source_url": "https://pace.ac.in/syllabus/CSE_IOT_R23.pdf", "document_type": "pdf"})


def test_scope_applies_before_top_k_and_missing_regulation_refuses(tmp_path):
    cfg = replace(settings, index_dir=tmp_path, vector_top_k=1, bm25_top_k=1)
    chunks = []
    for title, text, page in (
        ("AIML_R21", "aiml syllabus r23 regulation " * 30, 42),
        ("AIDS_R23", "aiml syllabus r23 regulation " * 20, 6),
        ("AIML_R23", "R-23 COURSE STRUCTURE\nII Year - I Semester\n1 P23CST05 Database Management Systems 3 0 0 3", 3),
    ):
        chunks.append({**_chunk(title, text, "academics"), "title": title,
                       "document_type": "pdf", "page": page,
                       "source_url": f"https://pace.ac.in/syllabus/{title}.pdf"})
    vectors = VectorStore(FakeEmbedder(), cfg)
    vectors.build(chunks)
    bm25 = BM25Search(cfg)
    bm25.build(chunks)
    retriever = HybridRetriever(vectors, bm25, cfg)
    llm = FakeLLM()
    result = RagPipeline(retriever, llm, cfg).ask("tell me the syllabus of aiml in r23 regulation")
    assert llm.calls == 0
    assert "Database Management Systems" in result["answer"]
    assert {x["title"] for x in result["sources"]} == {"AIML_R23"}
    assert not retriever.search("AIML R99 syllabus")["results"]


def test_course_table_skips_uncertain_rows():
    text = "II Year - I Semester\n1 P23CST05 Database Management Systems 3 0 0 3\n2 P23CST06 Broken title\n3 0 0 3"
    assert course_structure_excerpt(text) == [("II Year - I Semester", ["Database Management Systems"])]


def test_exact_overview_skips_inference_but_detailed_queries_do_not(tmp_path, monkeypatch):
    cfg = replace(settings, index_dir=tmp_path)
    chunk = {**_chunk("table", "COURSE STRUCTURE\nII Year - I Semester\n1 P23CST05 Database Management Systems 3 0 0 3", "academics"),
             "title": "AIML_R23", "document_type": "pdf", "page": 3,
             "source_url": "https://pace.ac.in/syllabus/AIML_R23.pdf"}
    vectors = VectorStore(FakeEmbedder(), cfg)
    vectors.build([chunk])
    bm25 = BM25Search(cfg)
    bm25.build([chunk])
    retriever = HybridRetriever(vectors, bm25, cfg)

    def forbidden(*args, **kwargs):
        raise AssertionError("hybrid search reached")

    monkeypatch.setattr(vectors, "search", forbidden)
    monkeypatch.setattr(bm25, "search", forbidden)
    result = retriever.search("AIML R23 syllabus")
    assert result["timing"]["retrieval_mode"] == "exact_syllabus"
    assert result["results"][0]["vector_score"] == 0
    assert "vector_rank" not in result["results"][0]
    for question in ("Explain database unit 2 in AIML R23 syllabus", "AIML syllabus",
                     "Compare AIML R23 and R21 syllabus"):
        with pytest.raises(AssertionError, match="hybrid search reached"):
            retriever.search(question)


def test_unparsed_overview_uses_hybrid_retrieval(tmp_path, monkeypatch):
    cfg = replace(settings, index_dir=tmp_path)
    vectors = VectorStore(FakeEmbedder(), cfg)
    vectors.build([{**_chunk("table", "COURSE STRUCTURE unreadable table", "academics"),
                    "title": "AIML_R23", "document_type": "pdf", "page": 3,
                    "source_url": "https://pace.ac.in/syllabus/AIML_R23.pdf"}])
    calls = []
    monkeypatch.setattr(vectors, "search", lambda *a: calls.append(a) or [])
    bm25 = BM25Search(cfg)
    bm25.build(vectors.records)
    HybridRetriever(vectors, bm25, cfg).search("AIML R23 syllabus")
    assert len(calls) == 1
