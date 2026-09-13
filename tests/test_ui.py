"""Exercise the actual Streamlit app without downloading or running models."""

from threading import Lock

from streamlit.testing.v1 import AppTest

from config import PROJECT_ROOT
from src import ui


class TestPipeline:
    __test__ = False

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def stream(self, question):
        self.calls.append(question)
        yield {"type": "token", "text": "See the official syllabus [S1]."}
        if self.fail:
            raise RuntimeError("Private diagnostic detail")
        yield {"type": "token", "text": "\n\nSources:\n[S1] Syllabus"}
        yield {
            "type": "complete",
            "sources": [{"title": "CSE R23", "url": "https://pace.ac.in/syllabus.pdf",
                         "page": 2, "document_type": "pdf"}],
            "retrieved": [],
            "timing": {"total_seconds": 0.2, "llm_seconds": 0.1},
        }


def make_app(monkeypatch, pipeline=None, ready=True):
    monkeypatch.setattr(ui, "knowledge_status", lambda: {"ready": ready, "pages": 120, "pdfs": 46})
    if pipeline is None:
        def no_load():
            raise AssertionError("The home screen must not load the backend")
        monkeypatch.setattr(ui, "backend", no_load)
    else:
        lock = Lock()
        monkeypatch.setattr(ui, "backend", lambda: (pipeline, lock))
    return AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=10)


def test_home_opens_without_models(monkeypatch):
    app = make_app(monkeypatch)
    assert not app.exception
    assert not app.chat_input[0].disabled
    assert app.button(key="suggest_01").label == "Explore courses  ↗"
    assert len(app.chat_input) == 1


def test_hi_does_not_load_backend_or_show_sources(monkeypatch):
    app = make_app(monkeypatch)
    app.chat_input[0].set_value("Hi").run()
    assert not app.exception
    answer = app.session_state["messages"][-1]
    assert answer["content"].startswith("Hi!")
    assert not answer["sources"]
    assert not answer.get("error")


def test_suggestion_stream_history_debug_and_clear(monkeypatch):
    pipeline = TestPipeline()
    app = make_app(monkeypatch, pipeline)
    app.button(key="suggest_02").click().run()
    assert not app.exception
    assert pipeline.calls == ["What is the CSE R23 syllabus?"]
    assert len(app.chat_message) == 2
    assert len(app.chat_input) == 1
    response = app.session_state["messages"][-1]
    assert response["content"] == "See the official syllabus [S1]."
    assert response["sources"][0]["page"] == 2
    app.toggle(key="debug_toggle").set_value(True).run()
    assert len(pipeline.calls) == 1  # rerenders must not generate again
    assert any(item.label == "Retrieval details" for item in app.expander)
    app.button(key="new_chat").click().run()
    assert not app.session_state["messages"]
    assert len(app.chat_message) == 0
    assert len(app.chat_input) == 1


def test_new_theme_has_motion_and_keyboard_accessibility():
    css = ui.asset_text("ui.css")
    assert "prefers-reduced-motion:reduce" in css
    assert "focus-visible" in css
    assert "max-width:760px" in css
    assert ".source-card:hover" in css
    assert ".hero-crest" in css
    assert ".chat-user-marker" in css


def test_typed_question_is_submitted_once(monkeypatch):
    pipeline = TestPipeline()
    app = make_app(monkeypatch, pipeline)
    app.chat_input[0].set_value("Where is the library?").run()
    assert not app.exception
    assert pipeline.calls == ["Where is the library?"]


def test_missing_index_disables_questions(monkeypatch):
    app = make_app(monkeypatch, ready=False)
    assert not app.exception
    assert app.chat_input[0].disabled
    assert app.button(key="suggest_01").disabled
    assert "prepared" in app.warning[0].value


def test_stream_failure_hides_partial_answer_and_allows_retry(monkeypatch):
    pipeline = TestPipeline(fail=True)
    app = make_app(monkeypatch, pipeline)
    app.chat_input[0].set_value("What is the syllabus?").run()
    assert not app.exception
    assert app.session_state["messages"][-1]["error"]
    assert "Private diagnostic" not in app.warning[0].value
    assert all("official syllabus" not in item.value for item in app.markdown)
    pipeline.fail = False
    app.chat_input[0].set_value("Try the syllabus again").run()
    assert not app.exception
    assert not app.session_state["messages"][-1].get("error")


def test_source_links_escape_content_and_reject_other_hosts():
    malicious = {"title": '<script>alert("x")</script>', "url": "https://pace.ac.in/syllabus.pdf",
                 "page": 2, "document_type": "pdf"}
    html = ui.source_cards([malicious])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'syllabus.pdf#page=2' in html
    for url in ("javascript:alert(1)", "https://pace.ac.in.evil.test/", "https://evil.test/", "https://user@pace.ac.in/"):
        assert ui.source_url({"url": url}) is None
