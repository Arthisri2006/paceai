"""Build the complete offline PACE knowledge base in one command."""

from __future__ import annotations

import argparse
import time
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

from config import settings
from src.bm25_search import BM25Search
from src.token_chunker import TokenDocumentChunker
from src.cleaner import TextCleaner
from src.crawler import PaceCrawler
from src.embeddings import EmbeddingModel
from src.pdf_loader import PacePdfLoader
from src.utils import load_json, save_json
from src.vector_store import VectorStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the PACE AI knowledge base")
    parser.add_argument("--max-pages", type=int, default=settings.max_pages)
    parser.add_argument("--max-depth", type=int, default=settings.max_depth)
    parser.add_argument("--max-pdfs", type=int, default=settings.max_pdfs)
    parser.add_argument("--reuse-crawl", action="store_true")
    parser.add_argument("--reuse-pdfs", action="store_true")
    parser.add_argument("--skip-pdfs", action="store_true")
    parser.add_argument("--force-embeddings", action="store_true")
    return parser.parse_args()


def build(args: argparse.Namespace) -> dict:
    if (settings.index_dir / "active.json").exists():
        raise ValueError("An immutable snapshot is selected. Build/evaluate a new candidate with tests.evaluate_token_index instead of overwriting the rollback index.")
    config = replace(
        settings,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        max_pdfs=args.max_pdfs,
    )
    config.ensure_directories()
    timings: dict[str, float] = {}
    total_started = time.perf_counter()

    started = time.perf_counter()
    if args.reuse_crawl:
        crawl = load_json(config.raw_dir / "crawl.json")
        if not crawl:
            raise FileNotFoundError("No saved crawl exists; remove --reuse-crawl.")
    else:
        crawl = PaceCrawler(config).crawl()
    timings["crawl_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    if args.skip_pdfs:
        pdf_result = {"documents": [], "stats": {"pdfs": 0, "pages": 0}}
    elif args.reuse_pdfs:
        pdf_result = load_json(config.raw_dir / "pdf_pages.json")
        if not pdf_result:
            raise FileNotFoundError("No saved PDF extraction exists; remove --reuse-pdfs.")
    else:
        pdf_result = PacePdfLoader(config).load_many(crawl["pdf_urls"])
    timings["pdf_seconds"] = round(time.perf_counter() - started, 3)

    started = time.perf_counter()
    embedder = EmbeddingModel(config)
    cleaned = TextCleaner(config).clean(crawl["pages"], pdf_result["documents"])
    chunk_result = TokenDocumentChunker(embedder.model.tokenizer, embedder.model.max_seq_length, config).chunk(cleaned["documents"])
    chunks = chunk_result["chunks"]
    timings["clean_chunk_seconds"] = round(time.perf_counter() - started, 3)

    fingerprint = index_fingerprint(chunks, config.embedding_model)
    previous_status = load_json(config.index_dir / "status.json", {})
    vector_files_exist = all(
        (config.index_dir / filename).exists()
        for filename in (VectorStore.INDEX_FILE, VectorStore.RECORDS_FILE)
    )
    can_reuse_vectors = (
        not args.force_embeddings
        and vector_files_exist
        and previous_status.get("fingerprint") == fingerprint
    )
    started = time.perf_counter()
    if not can_reuse_vectors:
        VectorStore(embedder, config).build(chunks)
    timings["embedding_faiss_seconds"] = round(time.perf_counter() - started, 3)
    timings["embeddings_reused"] = can_reuse_vectors

    started = time.perf_counter()
    BM25Search(config).build(chunks)
    timings["bm25_seconds"] = round(time.perf_counter() - started, 3)
    timings["total_seconds"] = round(time.perf_counter() - total_started, 3)

    status = {
        "ready": True,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
        "embedding_model": config.embedding_model,
        "pages": crawl["stats"]["pages"],
        "pdfs": pdf_result["stats"]["pdfs"],
        "pdf_pages": pdf_result["stats"]["pages"],
        "documents": cleaned["stats"]["clean_documents"],
        "chunks": len(chunks),
        "fingerprint": fingerprint,
        "chunking": {"strategy": "token-lines-v1", "token_limit": config.chunk_token_limit,
                     "overlap_tokens": config.chunk_token_overlap},
        "timing": timings,
    }
    save_json(config.index_dir / "status.json", status)
    return status


def index_fingerprint(chunks: list[dict], model: str) -> str:
    """Exact metadata/content identity, including provenance, case and schema."""
    payload = json.dumps({"schema": "token-lines-v1", "model": model, "chunks": chunks},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    outcome = build(_arguments())
    print("PACE knowledge base is ready.")
    for key, value in outcome.items():
        print(f"{key}: {value}")
