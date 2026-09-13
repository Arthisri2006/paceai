"""Repeatable, offline production-index benchmark. Does not generate or rebuild."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from src.runtime import load_pipeline
from src.utils import save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    pipeline = load_pipeline()
    report = {"load_seconds": round(time.perf_counter() - started, 6), "queries": []}
    store = pipeline.retriever.vector_store
    report.update(index_count=store.index.ntotal, embedding_dimensions=store.index.d)
    for question in (
        "What placement services are offered?",
        "What courses are offered at PACE?",
        "tell me the syllabus of aiml in r23 regulation",
        "What is in the AIML R99 syllabus?",
    ):
        runs = []
        for _ in range(4):
            started = time.perf_counter()
            retrieval, results, prompt = pipeline._prepare(question)
            runs.append({"seconds": round(time.perf_counter() - started, 6),
                         "timing": retrieval["timing"],
                         "ids": [x["chunk"]["id"] for x in results],
                         "prompt_characters": len(prompt or ""),
                         "prompt_words": len((prompt or "").split())})
        report["queries"].append({"question": question, "runs": runs})
    save_json(args.output, report)
    print(report)


if __name__ == "__main__":
    main()
