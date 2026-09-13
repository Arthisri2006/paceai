"""Offline regressions for the architecture/security audit."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests

from config import settings
from src.academic_query import is_course_overview
from src.chunker import DocumentChunker
from src.cleaner import TextCleaner
from src.pdf_loader import PacePdfLoader
from src.public_http import public_get
from src.rag_pipeline import RagPipeline
from src.retriever import HybridRetriever
from src.runtime import validate_indexes
from tests.test_rag import FakeLLM, FakeRetriever, _result


class HttpResponse:
    def __init__(self, status=200, headers=None, body=b"%PDF-example"):
        self.status_code = status
        self.headers = headers or {}
        self.body = body
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("test HTTP error")

    def iter_content(self, **kwargs):
        yield self.body


class HttpSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []
        self.headers = {}

    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        self.urls.append(url)
        return next(self.responses)


@pytest.mark.parametrize("url", ["https://evil.example/x", "http://127.0.0.1/x",
    "https://pace.ac.in:8443/x", "https://user:password@pace.ac.in/x", "file:///x"])
def test_public_download_rejects_untrusted_destination_before_request(url):
    session = HttpSession([])
    with pytest.raises(requests.RequestException):
        public_get(session, url, timeout=1)
    assert session.urls == []


@pytest.mark.parametrize("location", ["https://evil.example/x", "http://pace.ac.in/x", "//127.0.0.1/x"])
def test_redirect_rejected_before_destination_contact(location):
    response = HttpResponse(302, {"Location": location})
    session = HttpSession([response])
    with pytest.raises(requests.RequestException):
        public_get(session, "https://pace.ac.in/start", timeout=1)
    assert response.closed
    assert len(session.urls) == 1


def test_allowed_relative_redirect_and_loop_limit():
    first, final = HttpResponse(302, {"Location": "/new"}), HttpResponse()
    session = HttpSession([first, final])
    assert public_get(session, "https://pace.ac.in/old", timeout=1) is final
    assert session.urls[-1] == "https://pace.ac.in/new"
    assert first.closed and not final.closed
    responses = [HttpResponse(302, {"Location": "/loop"}) for _ in range(4)]
    with pytest.raises(requests.exceptions.TooManyRedirects):
        public_get(HttpSession(responses), "https://pace.ac.in/start", timeout=1)
    assert all(x.closed for x in responses)


@pytest.mark.parametrize("headers,body", [({"Content-Length": "999999999"}, b"%PDF-x"),
    ({}, b"not a PDF"), ({}, b"x" * (1024 * 1024 + 1))], ids=["declared-oversize", "bad-signature", "stream-oversize"])
def test_pdf_failures_close_response_and_remove_partial(tmp_path, headers, body):
    response = HttpResponse(headers=headers, body=body)
    loader = PacePdfLoader(replace(settings, raw_dir=tmp_path, request_delay=0, max_pdf_mb=1),
                           session=HttpSession([response]))
    with pytest.raises(ValueError):
        loader.download("https://pace.ac.in/a.pdf")
    assert response.closed
    assert not list(tmp_path.rglob("*.part"))


def test_valid_pdf_download_closes_and_reuses_file(tmp_path):
    response = HttpResponse()
    session = HttpSession([response])
    loader = PacePdfLoader(replace(settings, raw_dir=tmp_path, request_delay=0), session=session)
    path = loader.download("https://pace.ac.in/a.pdf")
    assert path.read_bytes() == response.body and response.closed
    assert loader.download("https://pace.ac.in/a.pdf") == path
    assert len(session.urls) == 1


def test_identical_text_keeps_different_document_and_page_provenance(tmp_path):
    config = replace(settings, cleaned_dir=tmp_path)
    # A long content line is not treated as a shared navigation/header line.
    base = {**_result()["chunk"], "text": "Meaningful shared academic content " * 12,
            "document_type": "pdf", "page": 1}
    other = {**base, "source_url": "https://pace.ac.in/other.pdf"}
    later = {**base, "page": 2}
    documents = TextCleaner(config).clean([], [base, other, later, base])["documents"]
    assert len(documents) == 3
    chunks = DocumentChunker(config).chunk(documents + [base])["chunks"]
    assert len(chunks) == 3
    assert len({(x["source_url"], x["page"]) for x in chunks}) == 3


@pytest.mark.parametrize("question", ["What courses are offered and their fees?",
    "What AIML courses are offered?", "What courses are offered in 2027?",
    "What courses are offered except Diploma?"])
def test_qualified_courses_question_cannot_use_generic_direct_answer(question):
    official = _result()
    official["chunk"]["source_url"] = "https://pace.ac.in/admissions/courses-offered"
    assert not is_course_overview(question)
    assert RagPipeline._direct_answer(question, [official]) is None


def test_context_citations_and_cards_share_page_identity():
    one, same, other = _result(), _result(), _result()
    same["chunk"]["id"] = "same-page-second-chunk"
    other["chunk"].update(id="other-page", page=2)
    pipe = RagPipeline(FakeRetriever([one, same, other]), FakeLLM())
    _, used, prompt = pipe._prepare("What placement services are offered?")
    assert prompt.count('"source": "[S1]"') == 2
    assert prompt.count('"source": "[S2]"') == 1
    assert "[S3]" not in prompt
    assert len(pipe._sources(used)) == 2


@pytest.mark.parametrize("text", ["A fabricated answer [S9].", "An answer without citations."])
def test_unknown_or_missing_citations_produce_transparent_fallback(text):
    class WrongLLM(FakeLLM):
        def stream(self, prompt):
            yield text
    answer = RagPipeline(FakeRetriever([_result()]), WrongLLM()).ask("Placement details?")
    assert answer["timing"]["answer_mode"] == "quality_fallback"
    assert not answer["sources"]
    assert text not in answer["answer"]


def test_cache_hit_isolated_from_mutation_and_top_k(monkeypatch):
    config = replace(settings, retrieval_cache_size=2, retrieval_cache_ttl=300)
    retriever = HybridRetriever(None, None, config)
    calls = []
    def search(question, top_k):
        calls.append((question, top_k))
        return {"results": [_result()], "timing": {"retrieval_seconds": 1}}
    monkeypatch.setattr(retriever, "_search", search)
    first = retriever.search("IT syllabus")
    first["results"].clear()
    second = retriever.search(" IT syllabus ")
    assert second["timing"]["cache_hit"] and second["results"]
    retriever.search("it syllabus")
    retriever.search("IT syllabus", top_k=1)
    retriever.search("IT syllabus")  # Least recently used entry was evicted.
    assert len(calls) == 4 and len(retriever._cache) == 2


def test_cache_expiry_and_disabled_cache(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("src.retriever.time.monotonic", lambda: clock[0])
    for size in (0, 2):
        retriever = HybridRetriever(None, None, replace(settings, retrieval_cache_size=size, retrieval_cache_ttl=5))
        monkeypatch.setattr(retriever, "_search", lambda *a: {"results": [], "timing": {}})
        assert not retriever.search("hello campus")["timing"]["cache_hit"]
        assert retriever.search("hello campus")["timing"]["cache_hit"] == bool(size)
        clock[0] += 6
        assert not retriever.search("hello campus")["timing"]["cache_hit"]


@pytest.mark.parametrize("question", ["", "  ", "x" * 1501, None])
def test_pipeline_rejects_invalid_question_before_retrieval(question):
    with pytest.raises(ValueError, match="1500"):
        RagPipeline(None, FakeLLM()).ask(question)


def test_index_consistency_and_embedding_identity():
    records = [_result()["chunk"]]
    vector = SimpleNamespace(records=records)
    bm25 = SimpleNamespace(chunks=deepcopy(records), corpus=[[]])
    validate_indexes(vector, bm25, {"embedding_model": "model-a"}, "model-a")
    with pytest.raises(ValueError, match="embedding model"):
        validate_indexes(vector, bm25, {"embedding_model": "model-a"}, "model-b")
    bm25.chunks[0]["text"] = "different snapshot"
    with pytest.raises(ValueError, match="inconsistent"):
        validate_indexes(vector, bm25, {"embedding_model": "model-a"}, "model-a")
