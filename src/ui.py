"""Small UI helpers; importing this module never loads an AI model."""

from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from threading import Lock
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import streamlit as st

from config import PROJECT_ROOT, settings
from src.utils import load_json
from src.index_selection import selection


ASSETS = PROJECT_ROOT / "assets"


def asset_text(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


@st.cache_data(show_spinner=False)
def logo_uri() -> str:
    data = base64.b64encode((ASSETS / "pace-logo.jpg").read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def knowledge_status() -> dict:
    try:
        index_dir = Path(selection(settings)[0])
        status = load_json(index_dir / "status.json", {})
        required = ("vectors.faiss", "vector_records.json", "bm25_corpus.json")
        status["ready"] = bool(status.get("ready")) and all(
            (index_dir / name).is_file() for name in required
        )
        return status
    except (ValueError, OSError, TypeError):
        return {"ready": False}


def refreshed_label(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value or "").strftime("%d %b %Y")
    except ValueError:
        return "Not yet indexed"


def backend():
    return _backend(selection(settings))


@st.cache_resource(show_spinner=False, max_entries=1)
def _backend(revision):
    # Deferred until the first submitted question, keeping initial UI startup light.
    from src.runtime import _load_pipeline

    # llama.cpp owns mutable generation state. Share one cached model and lock
    # across tabs; a second tab gets a friendly busy message instead of corruption.
    return _load_pipeline(revision), Lock()


def source_url(source: dict) -> str | None:
    """Only make official HTTP(S) sources clickable, including PDF page anchors."""
    try:
        parts = urlsplit(str(source.get("url", "")))
        if parts.scheme not in {"http", "https"} or parts.hostname not in {
            "pace.ac.in", "www.pace.ac.in"
        } or parts.username or parts.password or parts.port not in {
            None, 443 if parts.scheme == "https" else 80
        }:
            return None
        fragment = parts.fragment
        page = source.get("page")
        if isinstance(page, int) and not isinstance(page, bool) and page > 0:
            fragment = f"page={page}"
        return urlunsplit(parts._replace(fragment=fragment))
    except ValueError:
        return None


def source_cards(sources: list[dict]) -> str:
    cards = []
    for number, source in enumerate(sources, 1):
        url = source_url(source)
        if url is None:
            continue
        title = escape(str(source.get("title") or "Official PACE source"))
        page = source.get("page")
        kind = "PDF" if source.get("document_type") == "pdf" else "WEB PAGE"
        page_label = f" · PAGE {escape(str(page))}" if page else ""
        cards.append(
            f'<a class="source-card" data-spotlight href="{escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer" aria-label="Open source {number}: {title}">'
            f'<div class="source-kind"><span>S{number} · {kind}{page_label}</span><span>↗</span></div>'
            f'<div class="source-title">{title}</div>'
            '<div class="source-domain">pace.ac.in</div></a>'
        )
    return '<div class="source-grid">' + "".join(cards) + "</div>"


def answer_body(text: str) -> str:
    # Sources remain structured in the response and are rendered as cards below.
    return text.split("\n\nSources:", 1)[0].rstrip()


def render_details(message: dict, debug: bool) -> None:
    sources = message.get("sources", [])
    timing = message.get("timing", {})
    elapsed = timing.get("total_seconds")
    if elapsed is not None:
        count = len(sources)
        label = ("PACE AI" if timing.get("answer_mode") == "conversation" else
                 f'{count} official source{"s" if count != 1 else ""}' if count else
                 "Answer unavailable" if timing.get("answer_mode") == "quality_fallback" else
                 "No supporting source found")
        st.html(f'<div class="answer-meta">{label} &nbsp;·&nbsp; {float(elapsed):.1f}s</div>')
    if sources:
        st.html(source_cards(sources))
    used = {(s["url"], s.get("page")) for s in sources}
    related = []
    seen = set(used)
    for result in message.get("retrieved", []):
        chunk = result["chunk"]
        key = (chunk["source_url"], chunk.get("page"))
        if key in seen:
            continue
        seen.add(key)
        related.append({"url": key[0], "page": key[1], "title": chunk["title"],
                        "document_type": chunk["document_type"]})
    # Never present weak matches as useful sources for a refused answer.
    if sources and related:
        with st.expander("Other retrieved pages"):
            st.caption("Additional matches, not used as evidence for this answer.")
            st.html(source_cards(related))
    if debug:
        with st.expander("Retrieval details"):
            st.json(timing)
            for result in message.get("retrieved", []):
                chunk = result["chunk"]
                st.markdown(f'**{chunk["title"]}**')
                st.json({name: result.get(name, 0) for name in (
                    "vector_score", "bm25_score", "final_score", "intent_score"
                )})
                st.text(chunk["source_url"])
                st.text(chunk["text"])
