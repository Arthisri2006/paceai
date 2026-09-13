"""Build/evaluate an isolated candidate; never modifies the active index.

Uses cached local documents/model only. Gold evidence labels are in
retrieval_cases.json. Run with --output data/candidates/<new-name>.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np

from config import settings
from build_index import index_fingerprint
from src.bm25_search import BM25Search
from src.cleaner import TextCleaner
from src.embeddings import EmbeddingModel
from src.embedding_text import embedding_text
from src.rag_pipeline import RagPipeline
from src.retriever import HybridRetriever
from src.runtime import validate_indexes
from src.index_selection import FILES, digest
from src.token_chunker import TokenDocumentChunker
from src.utils import load_json, save_json
from src.vector_store import VectorStore


def evaluate(vectors, bm25, config, cases):
    pipeline = RagPipeline(HybridRetriever(vectors, bm25, replace(config, retrieval_cache_size=0)), None, config)
    results = []
    for case in cases:
        started = time.perf_counter()
        retrieved, used, prompt = pipeline._prepare(case["question"])
        def matches(item):
            chunk = item["chunk"]
            return (chunk["source_url"].endswith(case.get("source", "!"))
                    and (not case.get("pages") or chunk.get("page") in case["pages"])
                    and case.get("term", "").lower() in chunk["text"].lower())
        if case.get("unanswerable"):
            passed = prompt is None
        else:
            passed = any(matches(item) for item in used) and case.get("term", "").lower() in (prompt or "").lower()
            # Explicit regulation/branch cases must not mix other PDFs into context.
            if case.get("source", "").endswith(".pdf"):
                passed = passed and all(item["chunk"]["source_url"].endswith(case["source"]) for item in used)
        results.append({"id": case["id"], "question": case["question"], "passed": bool(passed),
                        "retrieval_mode": retrieved["timing"].get("retrieval_mode", "hybrid"),
                        "seconds": round(time.perf_counter() - started, 4),
                        "retrieved_hit": any(matches(item) for item in retrieved["results"]),
                        "context": [{"url": x["chunk"]["source_url"], "page": x["chunk"].get("page"),
                                     "id": x["chunk"]["id"]} for x in used]})
    return results


def finish_report(report, output):
    report["tested_sha256"] = {name: digest(output / name) for name in FILES}
    report["baseline_passed"] = sum(x["passed"] for x in report["baseline"])
    report["candidate_passed"] = sum(x["passed"] for x in report["candidate"])
    report["regressions"] = [b["id"] for a, b in zip(report["baseline"], report["candidate"], strict=True)
                             if (a["passed"] and not b["passed"])
                             or (a.get("retrieval_mode") == "exact_syllabus" and b.get("retrieval_mode") != "exact_syllabus")]
    report["eligible_for_promotion"] = not report["regressions"] and report["candidate_passed"] == len(report["candidate"])
    save_json(output / "evaluation.json", report)
    print({k: v for k, v in report.items() if k not in {"baseline", "candidate"}}, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-index", type=Path)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and not args.evaluate_only:
        raise ValueError("Choose a new candidate directory; existing output is never overwritten.")
    allowed = (settings.index_dir.parent / "candidates").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Candidate must be a new child of data/candidates.")
    output.mkdir(parents=True, exist_ok=args.evaluate_only)
    config = replace(settings, index_dir=output, cleaned_dir=output / "cleaned")
    embedder = EmbeddingModel(settings)
    model = embedder.model
    baseline = VectorStore(embedder, settings)
    baseline.load()
    baseline_bm25 = BM25Search(settings)
    baseline_bm25.load()
    status = load_json(settings.index_dir / "status.json")
    validate_indexes(baseline, baseline_bm25, status, settings.embedding_model)
    cases = load_json(Path(__file__).with_name("retrieval_cases.json"))
    if args.evaluate_only:
        candidate = VectorStore(embedder, config)
        candidate.load()
        candidate_bm25 = BM25Search(config)
        candidate_bm25.load()
        validate_indexes(candidate, candidate_bm25, load_json(output / "status.json"), settings.embedding_model)
        report = load_json(output / "evaluation.json")
        lengths = model.tokenizer([embedding_text(x) for x in candidate.records], truncation=False,
                                 return_length=True, padding=False, verbose=False)["length"]
        report.update(new_oversized=sum(x > model.max_seq_length for x in lengths),
                      new_max_tokens=max(lengths), candidate_chunks=len(candidate.records))
        report["baseline"] = evaluate(baseline, baseline_bm25, settings, cases)
        report["candidate"] = evaluate(candidate, candidate_bm25, config, cases)
        finish_report(report, output)
        return
    # Verify source/page/term labels exist, independently of the ranking results.
    raw_crawl = load_json(settings.raw_dir / "crawl.json")
    raw_pdf = load_json(settings.raw_dir / "pdf_pages.json")
    started = time.perf_counter()
    cleaned = TextCleaner(config).clean(raw_crawl["pages"], raw_pdf["documents"])
    for case in cases:
        if case.get("unanswerable"):
            continue
        assert any(d["source_url"].endswith(case["source"])
                   and (not case.get("pages") or d.get("page") in case["pages"])
                   and case["term"].lower() in d["text"].lower()
                   for d in cleaned["documents"]), f"Unverified gold label: {case['id']}"
    chunks = TokenDocumentChunker(model.tokenizer, model.max_seq_length, config).chunk(cleaned["documents"])["chunks"]
    lengths = model.tokenizer([embedding_text(x) for x in chunks], truncation=False,
                             return_length=True, padding=False, verbose=False)["length"]
    assert max(lengths) <= min(config.chunk_token_limit, model.max_seq_length)
    old_lengths = model.tokenizer([embedding_text(x) for x in baseline.records], truncation=False,
                                 return_length=True, padding=False, verbose=False)["length"]
    report = {"baseline_chunks": len(baseline.records), "candidate_chunks": len(chunks),
              "old_oversized": sum(x > model.max_seq_length for x in old_lengths),
              "new_oversized": sum(x > model.max_seq_length for x in lengths),
              "new_max_tokens": max(lengths), "model_window": model.max_seq_length,
              "clean_chunk_seconds": round(time.perf_counter() - started, 3)}
    report["baseline"] = evaluate(baseline, baseline_bm25, settings, cases)
    save_json(output / "evaluation.json", report)
    print(f"Candidate: {len(chunks)} chunks, maximum {max(lengths)} input tokens; baseline evaluated.", flush=True)
    # Reuse only exact canonical inputs already embedded by the same model and
    # fitting its window. This is a local build optimization, not query caching.
    existing = {embedding_text(chunk): baseline.index.reconstruct(i) for i, chunk in enumerate(baseline.records)
                if old_lengths[i] <= model.max_seq_length}
    if args.reuse_index:
        reuse_path = args.reuse_index.resolve()
        if not reuse_path.is_relative_to(allowed):
            raise ValueError("Reuse index must be a local candidate.")
        reuse_config = replace(settings, index_dir=reuse_path)
        reuse = VectorStore(embedder, reuse_config)
        reuse.load()
        reuse_bm25 = BM25Search(reuse_config)
        reuse_bm25.load()
        validate_indexes(reuse, reuse_bm25, load_json(reuse_path / "status.json"), settings.embedding_model)
        existing.update({embedding_text(chunk): reuse.index.reconstruct(i) for i, chunk in enumerate(reuse.records)})
    unique_new = list(dict.fromkeys(embedding_text(x) for x in chunks if embedding_text(x) not in existing))
    print(f"Embedding {len(unique_new)} new unique inputs using cached local BGE weights.", flush=True)
    started = time.perf_counter()
    encoded = embedder.encode_documents(unique_new)
    new_vectors = dict(zip(unique_new, encoded, strict=True))

    class ReusingEmbedder:
        def encode_documents(self, texts):
            return np.stack([existing[t] if t in existing else new_vectors[t] for t in texts])
        def encode_query(self, question):
            return embedder.encode_query(question)

    candidate = VectorStore(ReusingEmbedder(), config)
    candidate.build(chunks)
    bm25 = BM25Search(config)
    bm25.build(chunks)
    report["index_build_seconds"] = round(time.perf_counter() - started, 3)
    report["new_embedding_inputs"] = len(unique_new)
    new_status = {**status, "chunks": len(chunks), "documents": len(cleaned["documents"]),
                  "index_built_at": datetime.now(timezone.utc).isoformat(),
                  "fingerprint": index_fingerprint(chunks, settings.embedding_model),
                  "chunking": {"strategy": "token-lines-v1", "token_limit": config.chunk_token_limit,
                               "overlap_tokens": config.chunk_token_overlap}}
    # Preserve source refresh timestamp: saved documents were not downloaded again.
    save_json(output / "status.json", new_status)
    validate_indexes(candidate, bm25, new_status, settings.embedding_model)
    report["candidate"] = evaluate(candidate, bm25, config, cases)
    finish_report(report, output)


if __name__ == "__main__":
    main()
