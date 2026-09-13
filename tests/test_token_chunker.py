from dataclasses import replace
import re

import pytest

from config import settings
from src.token_chunker import TokenDocumentChunker
from src.embedding_text import embedding_text
from src.academic_query import course_structure_excerpt
from build_index import index_fingerprint
from src.embeddings import EmbeddingModel


class Tokenizer:
    """Deterministic offline tokenizer: punctuation also consumes budget."""
    def encode(self, text, **kwargs):
        return re.findall(r"\w+|[^\w\s]", text) + ["CLS", "SEP"]


def document(text):
    return {"text": text, "title": "AIML_R23", "source_url": "https://pace.ac.in/AIML_R23.pdf",
            "document_type": "pdf", "page": 3, "category": "academics"}


def chunker(tmp_path, limit=90):
    return TokenDocumentChunker(Tokenizer(), 512, replace(settings, cleaned_dir=tmp_path,
                                chunk_token_limit=limit, chunk_token_overlap=12))


def test_complete_embedding_input_bounded_and_every_row_keeps_semester(tmp_path):
    rows = [f"{i} P23CST{i:02d} Subject Number {i} 3 0 0 3" for i in range(1, 21)]
    heading = "II Year - I Semester"
    chunks = chunker(tmp_path).chunk([document("COURSE STRUCTURE\n" + heading + "\n" + "\n".join(rows))])["chunks"]
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(Tokenizer().encode(embedding_text(chunk))) <= 90
        if "P23CST" in chunk["text"]:
            assert heading in chunk["text"]
            assert "COURSE STRUCTURE" in chunk["text"]
            assert course_structure_excerpt(chunk["text"])
        assert chunk["page"] == 3 and chunk["source_url"].endswith("AIML_R23.pdf")
    assert all(any(row in c["text"] for c in chunks) for row in rows)


def test_long_line_tail_not_truncated(tmp_path):
    words = [f"unique{i}" for i in range(400)]
    chunks = chunker(tmp_path).chunk([document(" ".join(words))])["chunks"]
    assert all(any(word in c["text"].split() for c in chunks) for word in words)
    assert all(len(Tokenizer().encode(embedding_text(c))) <= 90 for c in chunks)


def test_same_text_different_sources_survive_and_small_text_unchanged(tmp_path):
    original = document("First meaningful line.\nSecond meaningful line.")
    other = {**original, "source_url": "https://pace.ac.in/AIML_R21.pdf", "title": "AIML_R21"}
    chunks = chunker(tmp_path).chunk([original, other])["chunks"]
    assert len(chunks) == 2 and chunks[0]["text"] == original["text"]


def test_invalid_budget_or_oversized_metadata_fails_explicitly(tmp_path):
    with pytest.raises(ValueError):
        chunker(tmp_path, 20)
    with pytest.raises(ValueError, match="metadata"):
        chunker(tmp_path).chunk([{**document("short"), "title": "huge title " * 200}])


def test_fingerprint_covers_case_provenance_and_document_type():
    base = document("Relevant text")
    fingerprint = index_fingerprint([base], "model")
    for field, value in (("text", "relevant text"), ("page", 4), ("document_type", "webpage"),
                         ("source_url", "https://pace.ac.in/other.pdf")):
        assert index_fingerprint([{**base, field: value}], "model") != fingerprint
    assert index_fingerprint([base], "other-model") != fingerprint


def test_embedding_rejects_truncation_before_inference():
    class Model:
        max_seq_length = 512
        tokenizer = staticmethod(lambda *a, **k: {"length": [513]})
        def encode(self, *a, **k):
            pytest.fail("Oversized input must not reach inference")
    embedder = EmbeddingModel()
    embedder.__dict__["model"] = Model()
    with pytest.raises(ValueError, match="silent truncation"):
        embedder.encode_documents(["oversized fixture"])


def test_split_overview_retains_rows_across_two_pdf_pages(tmp_path):
    from src.retriever import HybridRetriever
    from src.rag_pipeline import RagPipeline
    from src.vector_store import VectorStore
    from src.bm25_search import BM25Search
    from tests.test_retrieval import FakeEmbedder
    from tests.test_rag import FakeLLM
    config = replace(settings, index_dir=tmp_path, cleaned_dir=tmp_path,
                     chunk_token_limit=90, chunk_token_overlap=12)
    documents = []
    expected = []
    for page in (2, 3):
        rows = [f"{i} P23CST{i:02d} Course Page {page} Number {i} 3 0 0 3" for i in range(1, 12)]
        expected.extend(f"Course Page {page} Number {i}" for i in range(1, 12))
        documents.append({**document("COURSE STRUCTURE\nII Year - I Semester\n" + "\n".join(rows)), "page": page})
    chunks = TokenDocumentChunker(Tokenizer(), 512, config).chunk(documents)["chunks"]
    vectors = VectorStore(FakeEmbedder(), config)
    vectors.build(chunks)
    bm25 = BM25Search(config)
    bm25.build(chunks)
    llm = FakeLLM()
    result = RagPipeline(HybridRetriever(vectors, bm25, config), llm, config).ask("AIML R23 syllabus")
    assert llm.calls == 0 and {x["page"] for x in result["sources"]} == {2, 3}
    assert all(subject in result["answer"] for subject in expected)
