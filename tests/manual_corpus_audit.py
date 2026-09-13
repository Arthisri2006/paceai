"""Offline corpus diagnostics; writes only a report and temporary clean output."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import tempfile
import time

from config import settings
from src.chunker import DocumentChunker
from src.cleaner import TextCleaner
from src.embeddings import EmbeddingModel
from src.utils import load_json, save_json
from src.vector_store import VectorStore


def main():
    records = load_json(settings.index_dir / "vector_records.json")
    lengths = sorted(len(x["text"].split()) for x in records)
    model = EmbeddingModel().model
    tokens = model.tokenizer([VectorStore._searchable_text(x) for x in records],
                            truncation=False, padding=False, return_length=True, verbose=False)["length"]
    report = {"existing_chunks": len(records), "model_max_seq_length": model.max_seq_length,
              "embedding_inputs_exceeding_token_window": sum(x > model.max_seq_length for x in tokens),
              "chunk_words": {"min": lengths[0], "median": lengths[len(lengths)//2],
                              "p95": lengths[int(len(lengths)*.95)], "max": lengths[-1]},
              "document_types": dict(Counter(x["document_type"] for x in records))}
    crawl = load_json(settings.raw_dir / "crawl.json")
    pdfs = load_json(settings.raw_dir / "pdf_pages.json")
    with tempfile.TemporaryDirectory(prefix="pace-audit-") as directory:
        config = replace(settings, cleaned_dir=Path(directory))
        started = time.perf_counter()
        cleaned = TextCleaner(config).clean(crawl["pages"], pdfs["documents"])
        chunks = DocumentChunker(config).chunk(cleaned["documents"])
        report.update(dry_run_clean_chunk_seconds=round(time.perf_counter() - started, 4),
                      dry_run_clean_stats=cleaned["stats"], dry_run_chunk_stats=chunks["stats"])
    save_json(settings.index_dir / "audit_corpus.json", report)
    print(report)


if __name__ == "__main__":
    main()
