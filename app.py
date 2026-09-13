"""PACE AI student workspace. Start with: streamlit run app.py"""

from __future__ import annotations

import logging
import time

import streamlit as st

from config import settings
from src.answer_policy import conversational_reply
from src.ui import (
    ASSETS, answer_body, asset_text, backend, knowledge_status, logo_uri,
    refreshed_label, render_details,
)


st.set_page_config(page_title="PACE AI · Your campus assistant", page_icon=str(ASSETS / "pace-logo.jpg"),
                   layout="wide", initial_sidebar_state="expanded")
st.html(f'<style>{asset_text("ui.css")}</style>')
# This script is a checked-in asset. No question, answer, or source text enters it.
st.html(f'<script>{asset_text("spotlight.js")}</script>', unsafe_allow_javascript=True)
st.session_state.setdefault("messages", [])
status = knowledge_status()
ready = status.get("ready", False)
uses_gemini = settings.llm_provider.lower() == "gemini"


def clear_chat() -> None:
    st.session_state.messages = []
    st.session_state.pop("pending_question", None)


def ask_suggestion(question: str) -> None:
    st.session_state.pending_question = question


with st.sidebar:
    st.html(f'<div class="brand"><img src="{logo_uri()}" alt="PACE Institute crest">'
            '<div><div class="brand-title">PACE <span>AI</span></div>'
            '<div class="brand-sub">Your campus companion</div></div></div>')
    st.button("＋  New conversation", key="new_chat", on_click=clear_chat, width="stretch")
    st.html('<div class="side-label">Workspace</div>')
    st.html('<div class="side-active" aria-current="page">✦ &nbsp; Campus assistant</div>')
    st.link_button("PACE website  ↗", "https://pace.ac.in/", width="stretch")
    st.html('<div class="side-label">Your knowledge library</div>')
    dot = "" if ready else " offline"
    state_label = "Ready to explore" if ready else "Setup needed"
    st.html(f'<div class="kb-summary" data-spotlight><strong><span class="status-dot{dot}"></span>'
            f'{state_label}</strong><p>Answers drawn from official PACE webpages and academic documents.</p></div>')
    with st.expander("Library details"):
        left, right = st.columns(2)
        left.metric("Webpages", status.get("pages", 0))
        right.metric("Documents", status.get("pdfs", 0))
        st.caption(f'Last indexed · {refreshed_label(status.get("last_refreshed"))}')
        st.caption(f'{status.get("chunks", 0):,} searchable passages')
        st.caption(f'{status.get("pdf_pages", 0):,} PDF pages')
        st.caption("Saved locally. Opening this app does not refresh the library.")
    st.html('<div class="side-label">Preferences</div>')
    debug = st.toggle("Show retrieval details", value=settings.debug, key="debug_toggle")
    with st.expander("Answer model"):
        model_name = settings.gemini_model if uses_gemini else settings.llm_gguf_repo if settings.llm_provider == "llama_cpp" else settings.llm_model
        st.caption(model_name)
        st.caption("Gemini receives your question and retrieved PACE excerpts. Search runs locally."
                   if uses_gemini else "Runs on this computer. Model settings can be changed in .env.")
        if uses_gemini and not settings.gemini_api_key.strip():
            st.warning("Gemini key needed: add GEMINI_API_KEY to .env and restart.")
    st.html('<div class="side-footer"><span class="status-dot"></span>Valluru, Ongole<br>'
            '<span>PACE Institute of Technology &amp; Sciences</span></div>')

provider_badge = "Gemini · key needed" if uses_gemini and not settings.gemini_api_key.strip() else "Gemini · online" if uses_gemini else "Local &amp; private"
st.html(f'<div class="workspace-header"><div class="workspace-label">PACE AI<span class="workspace-subtitle">Campus assistant</span></div>'
        f'<div class="local-badge"><span class="status-dot"></span>{provider_badge}</div></div>')

if not ready:
    st.warning("Your campus library needs to be prepared before you can ask questions.")
    with st.expander("Set up the knowledge library", expanded=True):
        st.write("Run this once from the project folder, then reload this page:")
        st.code("python build_index.py", language="bash")

typed = None
if not st.session_state.messages:
    st.html(f'<div class="hero"><div class="hero-crest"><img src="{logo_uri()}" alt="PACE Institute crest"></div>'
            '<h1>Hello, PACE.</h1><p>What would you like to know?</p></div>')
    with st.container(key="home_composer"):
        typed = st.chat_input("Ask anything about PACE…", disabled=not ready, max_chars=1500)
    st.html('<div class="section-heading">A little inspiration to get started</div>')
    topics = [
        ("01", "◎", "Explore courses", "Find the right path for you",
         "Explore courses  ↗", "What courses are offered at PACE?"),
        ("02", "▤", "Find your syllabus", "Subjects, semesters & regulations",
         "Find CSE R23 syllabus  ↗", "What is the CSE R23 syllabus?"),
        ("03", "↗", "Plan your next step", "Training & placement support",
         "Discover placements  ↗", "What placement services are offered?"),
    ]
    for column, (number, icon, title, description, label, question) in zip(st.columns(3, gap="small"), topics):
        with column, st.container(key=f"topic_{number}"):
            st.html(f'<div class="topic-top" aria-hidden="true"><span>{icon}</span></div>'
                    f'<div class="topic-title">{title}</div><div class="topic-desc">{description}</div>')
            st.button(label, key=f"suggest_{number}", on_click=ask_suggestion,
                      args=(question,), disabled=not ready, width="stretch")
    with st.container(key="quick_prompts", horizontal=True, gap="small"):
        for label, question in (
            ("Hostel & campus", "What hostel facilities are available?"),
            ("Admissions", "What information is available about admissions?"),
            ("Student services", "What is available under student services?"),
        ):
            st.button(label, key=f"quick_{label}", on_click=ask_suggestion,
                      args=(question,), disabled=not ready)
    st.html('<div class="trust-line">Grounded in official PACE sources. Always check the linked documents.</div>')
else:
    st.html('<div class="chat-intro">Your conversation</div>')

for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar=str(ASSETS / "pace-logo.jpg") if message["role"] == "assistant" else ":material/person:"):
        if message["role"] == "user":
            st.html('<span class="chat-user-marker" aria-hidden="true"></span>')
        if message.get("error"):
            st.warning(message["content"])
        else:
            st.markdown(message["content"])
        if message["role"] == "assistant":
            render_details(message, debug)

if st.session_state.messages:
    typed = st.chat_input("Ask anything about PACE…", disabled=not ready, max_chars=1500)
question = typed or st.session_state.pop("pending_question", None)
if question and ready:
    question = question.strip()
    if not question:
        st.stop()
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=":material/person:"):
        st.html('<span class="chat-user-marker" aria-hidden="true"></span>')
        st.markdown(question)
    with st.chat_message("assistant", avatar=str(ASSETS / "pace-logo.jpg")):
        indicator = st.empty()
        indicator.caption("Searching the campus library…")
        output = st.empty()
        text = ""
        completed = None
        started = time.perf_counter()
        first_text = None
        backend_seconds = 0.0
        lock = None
        acquired = False
        try:
            greeting = conversational_reply(question)
            if greeting is not None:
                events = iter([{"type": "token", "text": greeting},
                               {"type": "complete", "sources": [], "retrieved": [],
                                "timing": {"retrieval_seconds": 0.0, "llm_seconds": 0.0,
                                           "total_seconds": 0.0, "answer_mode": "conversation"}}])
            else:
                backend_started = time.perf_counter()
                pipeline, lock = backend()
                backend_seconds = time.perf_counter() - backend_started
                acquired = lock.acquire(blocking=False)
                if not acquired:
                    raise BlockingIOError("Another answer is in progress")
                events = pipeline.stream(question)
            last_draw = 0.0
            for event in events:
                if event["type"] == "token":
                    text += event["text"]
                    now = time.perf_counter()
                    if first_text is None:
                        first_text = now - started
                        indicator.empty()
                    # Limit browser updates to ten per second; model tokens keep streaming.
                    if now - last_draw >= 0.1:
                        output.markdown(answer_body(text) + " ▍")
                        last_draw = now
                elif event["type"] == "complete":
                    completed = event
                elif event["type"] == "replace":
                    text = event["text"]
                    output.markdown(text)
            if completed is None or not text.strip():
                raise RuntimeError("Incomplete answer stream")
            response = {"role": "assistant", "content": answer_body(text),
                        "sources": completed.get("sources", []),
                        "retrieved": completed.get("retrieved", []),
                        "timing": {**completed.get("timing", {}),
                                   "pipeline_seconds": completed.get("timing", {}).get("total_seconds", 0.0),
                                   "backend_initialize_seconds": round(backend_seconds, 3),
                                   "total_seconds": round(time.perf_counter() - started, 3),
                                   "first_text_seconds": round(first_text or 0, 3)}}
            output.markdown(response["content"])
            render_details(response, debug)
        except Exception as error:
            from src.llm import LLMServiceError
            # Provider failures have safe text. Never log raw request details.
            logging.getLogger(__name__).warning("PACE answer failed (%s)", type(error).__name__)
            text = ("Another answer is running in a different tab. Please try again shortly."
                    if isinstance(error, BlockingIOError) else
                    str(error) if isinstance(error, LLMServiceError) else
                    "I couldn't finish that answer. Please try again. If this continues, check the local model and library setup.")
            output.empty()
            st.warning(text)
            response = {"role": "assistant", "content": text, "error": True}
        finally:
            indicator.empty()
            if acquired and lock is not None:
                lock.release()
        st.session_state.messages.append(response)
    st.rerun()
