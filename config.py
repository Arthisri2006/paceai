"""Central, environment-driven settings for PACE AI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All tunable values live here so beginners have one place to look."""

    base_url: str = os.getenv("PACE_BASE_URL", "https://pace.ac.in/")
    user_agent: str = os.getenv(
        "PACE_USER_AGENT",
        "PACE-AI-Academic-Assistant/1.0 (+https://pace.ac.in/)",
    )
    request_timeout: int = int(os.getenv("PACE_REQUEST_TIMEOUT", "20"))
    request_delay: float = float(os.getenv("PACE_REQUEST_DELAY", "0.75"))
    max_pages: int = int(os.getenv("PACE_MAX_PAGES", "120"))
    max_depth: int = int(os.getenv("PACE_MAX_DEPTH", "3"))
    max_pdfs: int = int(os.getenv("PACE_MAX_PDFS", "80"))
    max_pdf_mb: int = int(os.getenv("PACE_MAX_PDF_MB", "40"))

    chunk_size: int = int(os.getenv("PACE_CHUNK_SIZE", "600"))
    chunk_overlap: int = int(os.getenv("PACE_CHUNK_OVERLAP", "100"))
    chunk_token_limit: int = int(os.getenv("PACE_CHUNK_TOKEN_LIMIT", "448"))
    chunk_token_overlap: int = int(os.getenv("PACE_CHUNK_TOKEN_OVERLAP", "48"))
    embedding_model: str = os.getenv(
        "PACE_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
    )
    embedding_batch_size: int = int(os.getenv("PACE_EMBEDDING_BATCH_SIZE", "32"))

    vector_top_k: int = int(os.getenv("PACE_VECTOR_TOP_K", "8"))
    bm25_top_k: int = int(os.getenv("PACE_BM25_TOP_K", "8"))
    final_top_k: int = int(os.getenv("PACE_FINAL_TOP_K", "4"))
    max_chunks_per_source: int = int(os.getenv("PACE_MAX_CHUNKS_PER_SOURCE", "2"))
    vector_weight: float = float(os.getenv("PACE_VECTOR_WEIGHT", "0.50"))
    bm25_weight: float = float(os.getenv("PACE_BM25_WEIGHT", "0.50"))
    use_cross_encoder: bool = _env_bool("PACE_USE_CROSS_ENCODER", False)
    reranker_model: str = os.getenv(
        "PACE_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )
    min_retrieval_score: float = float(os.getenv("PACE_MIN_RETRIEVAL_SCORE", "0.35"))
    min_vector_evidence: float = float(os.getenv("PACE_MIN_VECTOR_EVIDENCE", "0.58"))
    min_lexical_evidence: float = float(os.getenv("PACE_MIN_LEXICAL_EVIDENCE", "0.25"))
    max_context_words: int = int(os.getenv("PACE_MAX_CONTEXT_WORDS", "900"))
    max_context_sources: int = int(os.getenv("PACE_MAX_CONTEXT_SOURCES", "3"))
    retrieval_cache_size: int = int(os.getenv("PACE_RETRIEVAL_CACHE_SIZE", "128"))
    retrieval_cache_ttl: float = float(os.getenv("PACE_RETRIEVAL_CACHE_TTL", "300"))

    # The 1.5B model is the responsive default for a 16 GB, CPU-only machine.
    # Set PACE_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct for a slower quality upgrade.
    llm_model: str = os.getenv("PACE_LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    llm_provider: str = os.getenv("PACE_LLM_PROVIDER", "llama_cpp")
    gemini_model: str = os.getenv("PACE_GEMINI_MODEL", "gemini-3.5-flash")
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""), repr=False)
    gemini_max_output_tokens: int = int(os.getenv("PACE_GEMINI_MAX_OUTPUT_TOKENS", "1024"))
    gemini_timeout: int = int(os.getenv("PACE_GEMINI_TIMEOUT", "45"))
    llm_gguf_repo: str = os.getenv(
        "PACE_LLM_GGUF_REPO", "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    )
    llm_gguf_filename: str = os.getenv(
        "PACE_LLM_GGUF_FILENAME", "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    )
    llm_context_size: int = int(os.getenv("PACE_LLM_CONTEXT_SIZE", "4096"))
    llm_threads: int = int(os.getenv("PACE_LLM_THREADS", "8"))
    llm_max_new_tokens: int = int(os.getenv("PACE_LLM_MAX_NEW_TOKENS", "160"))
    debug: bool = _env_bool("PACE_DEBUG", False)

    raw_dir: Path = field(default=PROJECT_ROOT / "data" / "raw")
    cleaned_dir: Path = field(default=PROJECT_ROOT / "data" / "cleaned")
    index_dir: Path = field(default=PROJECT_ROOT / "data" / "index")
    cache_dir: Path = field(default=PROJECT_ROOT / "data" / "cache")

    def ensure_directories(self) -> None:
        for path in (self.raw_dir, self.cleaned_dir, self.index_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
