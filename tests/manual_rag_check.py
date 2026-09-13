"""End-to-end local answer, streaming, citation, and latency acceptance check."""

from __future__ import annotations

import time

from config import settings
from src.runtime import load_pipeline
from src.utils import save_json


QUESTIONS = (
    "What courses are offered at PACE?",
    "What placement services are offered?",
    "What is the CSE R23 syllabus?",
    "Who won the FIFA World Cup in 2030?",
)


def main() -> None:
    pipeline = load_pipeline()
    report: list[dict] = []
    for question in QUESTIONS:
        started = time.perf_counter()
        first_token_seconds: float | None = None
        answer_parts: list[str] = []
        completed: dict = {}
        for event in pipeline.stream(question):
            if event["type"] == "token":
                if first_token_seconds is None:
                    first_token_seconds = time.perf_counter() - started
                answer_parts.append(event["text"])
            elif event["type"] == "replace":
                answer_parts = [event["text"]]
            elif event["type"] == "complete":
                completed = event
        answer = "".join(answer_parts)
        entry = {
            "question": question,
            "answer": answer,
            "first_token_seconds": (
                round(first_token_seconds, 4) if first_token_seconds is not None else None
            ),
            "timing": completed["timing"],
            "sources": completed["sources"],
        }
        report.append(entry)
        print(f"\nQ: {question}\n{answer}")
        print(f"\nFirst token: {entry['first_token_seconds']} seconds")
        print(f"Total: {entry['timing']['total_seconds']} seconds")
    save_json(settings.index_dir / "rag_acceptance.json", report)


if __name__ == "__main__":
    main()
