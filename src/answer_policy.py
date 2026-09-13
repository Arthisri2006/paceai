"""Cheap conversational routing and bounded streaming quality checks."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator


NOT_FOUND = "I could not find this information in the indexed PACE sources."


def conversational_reply(question: str) -> str | None:
    text = re.sub(r"[^a-z0-9 ]", " ", question.lower())
    text = " ".join(text.split())
    if text in {"hi", "hello", "hey", "hello pace", "hi pace", "hi pace ai", "hello pace ai",
                "good morning", "good afternoon", "good evening"}:
        return "Hi! I'm PACE AI. I can help you find courses, syllabi, admissions, placements, and campus information. What would you like to know?"
    if text in {"thanks", "thank you", "thank you so much", "thanks a lot"}:
        return "You're welcome! Let me know if you need anything else about PACE."
    if text in {"help", "what can you do", "how can you help me"}:
        return "I can help you find information in official PACE webpages and PDFs. Try asking for your branch and regulation's syllabus, admission information, or campus facilities."
    return None


class AnswerQualityError(RuntimeError):
    """Generation repeated itself or produced no usable answer."""


def repetitive(text: str) -> bool:
    words = re.findall(r"\w+", text.lower())
    phrases = Counter(tuple(words[i:i + 8]) for i in range(len(words) - 7))
    return any(count >= 3 for count in phrases.values())


def guarded_text(tokens: Iterator[str]) -> Iterator[str]:
    """Check complete sentences before releasing them; close on a bad stream.

    This adds at most a sentence of buffering, and avoids showing the repeated
    token loop while it is being generated. The caller can replace prior output
    with a transparent fallback if the generation fails quality checks.
    """
    pending = ""
    accepted = ""
    seen: set[str] = set()
    try:
        for token in tokens:
            pending += token
            if repetitive(accepted + pending):
                raise AnswerQualityError("Repeated phrase loop")
            while match := re.search(r"[.!?](?=\s)", pending):
                end = match.end()
                sentence, pending = pending[:end], pending[end:]
                canonical = " ".join(re.findall(r"\w+", sentence.lower()))
                if len(canonical.split()) >= 5 and canonical in seen:
                    raise AnswerQualityError("Repeated sentence")
                seen.add(canonical)
                accepted += sentence
                yield sentence
        if pending.strip():
            canonical = " ".join(re.findall(r"\w+", pending.lower()))
            if len(canonical.split()) >= 5 and canonical in seen:
                raise AnswerQualityError("Repeated final sentence")
            if pending.rstrip().endswith((".", "!", "?", "]")):
                accepted += pending
                yield pending
            elif not accepted.strip():
                raise AnswerQualityError("Truncated answer")
            # Drop a final incomplete sentence when earlier sentences exist.
        if not accepted.strip():
            raise AnswerQualityError("Empty answer")
    finally:
        close = getattr(tokens, "close", None)
        if close:
            close()
