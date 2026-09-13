"""Offline checks for the Gemini transport and credential handling."""

import json
from dataclasses import replace

import pytest
import requests

from config import settings
from src.llm import GeminiLLM, LLMServiceError


class Response:
    status_code = 200

    def __init__(self, lines=(), status=200):
        self.lines = lines
        self.status_code = status
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_lines(self, **kwargs):
        yield from self.lines


def config(key="test-secret"):
    return replace(settings, llm_provider="gemini", gemini_api_key=key, gemini_model="gemini-3.5-flash")


def test_stream_keeps_key_in_header_and_filters_thoughts(monkeypatch):
    event = {"candidates": [{"content": {"parts": [
        {"text": "private reasoning", "thought": True}, {"text": "Grounded answer [S1]."}
    ]}, "finishReason": "STOP"}]}
    response = Response(["data: " + json.dumps(event), "", "data: [DONE]", ""])

    def post(url, **kwargs):
        assert "test-secret" not in url
        assert kwargs["headers"]["x-goog-api-key"] == "test-secret"
        assert kwargs["allow_redirects"] is False
        assert kwargs["json"]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "MINIMAL"
        assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "question and excerpts"
        return response

    monkeypatch.setattr(requests, "post", post)
    assert GeminiLLM(config()).generate("question and excerpts") == "Grounded answer [S1]."
    assert response.closed
    assert "test-secret" not in repr(config())


def test_missing_key_never_calls_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing key must not contact provider")

    monkeypatch.setattr(requests, "post", forbidden)
    with pytest.raises(LLMServiceError, match="Add GEMINI_API_KEY"):
        GeminiLLM(config("")).generate("question")


@pytest.mark.parametrize("status,match", [(403, "denied"), (429, "quota"), (500, "unavailable")])
def test_http_errors_are_safe(monkeypatch, status, match):
    response = Response(status=status)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    with pytest.raises(LLMServiceError, match=match) as caught:
        GeminiLLM(config()).generate("question")
    assert "test-secret" not in str(caught.value)
    assert response.closed


def test_connection_errors_hide_raw_provider_details(monkeypatch):
    def post(*args, **kwargs):
        raise requests.Timeout("provider detail test-secret")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(LLMServiceError, match="internet connection") as caught:
        GeminiLLM(config()).generate("question")
    assert "test-secret" not in str(caught.value)


def test_malformed_stream_is_safe(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(["data: not-json", ""]))
    with pytest.raises(LLMServiceError, match="unreadable"):
        GeminiLLM(config()).generate("question")


@pytest.mark.parametrize("event", [[], {"candidates": [None]}, {"usageMetadata": []},
    {"candidates": [{"content": {"parts": [{"text": 123}]}}]}])
def test_unexpected_stream_shapes_are_safe(monkeypatch, event):
    response = Response(["data: " + json.dumps(event), ""])
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    with pytest.raises(LLMServiceError):
        GeminiLLM(config()).generate("question")
    assert response.closed


def test_usage_is_request_local_and_premature_eof_is_rejected(monkeypatch):
    event = {"candidates": [{"content": {"parts": [{"text": "Answer [S1]."}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 8, "totalTokenCount": 108}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(["data: " + json.dumps(event), ""]))
    usage = {}
    assert "".join(GeminiLLM(config()).stream_with_usage("question", usage)) == "Answer [S1]."
    assert usage == {"promptTokenCount": 100, "candidatesTokenCount": 8, "totalTokenCount": 108, "finishReason": "STOP"}
    del event["candidates"][0]["finishReason"]
    with pytest.raises(LLMServiceError, match="ended early"):
        GeminiLLM(config()).generate("question")
