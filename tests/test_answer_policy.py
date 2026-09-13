import pytest

from src.answer_policy import conversational_reply, guarded_text, AnswerQualityError, NOT_FOUND
from src.rag_pipeline import RagPipeline
from src.llm import BaseLLM
from tests.test_rag import FakeRetriever, FakeLLM, _result


def test_greeting_skips_retrieval_and_generation():
    class NoSearch:
        def search(self, question):
            raise AssertionError("Greeting must not search")
    llm = FakeLLM()
    result = RagPipeline(NoSearch(), llm).ask("Hi!")
    assert result["answer"].startswith("Hi!")
    assert result["sources"] == []
    assert result["timing"]["retrieval_seconds"] == 0
    assert llm.calls == 0
    assert conversational_reply("Hi, what is the AIML syllabus?") is None


def test_repetitive_stream_is_closed():
    closed = []
    def tokens():
        try:
            yield "The syllabus includes tasks like installing BOSS on the computer. "
            while True:
                yield "The syllabus includes tasks like installing BOSS on the computer. "
        finally:
            closed.append(True)
    with pytest.raises(AnswerQualityError):
        list(guarded_text(tokens()))
    assert closed


@pytest.mark.parametrize("answer", [NOT_FOUND, "The syllabus includes tasks like installing BOSS on the computer. " * 5])
def test_refusal_or_repetition_removes_irrelevant_source_cards(answer):
    class Stub(BaseLLM):
        def stream(self, prompt):
            yield answer
    result = RagPipeline(FakeRetriever([_result()]), Stub()).ask("Explain the syllabus")
    assert result["sources"] == []
    assert "Sources:" not in result["answer"]
    assert "installing BOSS" not in result["answer"]


def test_complete_sentence_survives_truncated_tail():
    assert "".join(guarded_text(iter(["The library has books. The library also has"]))) == "The library has books."
