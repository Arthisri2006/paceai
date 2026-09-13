"""Lazy, reusable BGE embedding model wrapper."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from config import Settings, settings


BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingModel:
    """Load the embedding model once and return cosine-ready vectors."""

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @cached_property
    def model(self) -> SentenceTransformer:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        cache_root = self.config.cache_dir / "models"
        model_cache = cache_root / f"models--{self.config.embedding_model.replace('/', '--')}"
        # Once downloaded, never perform network update checks during chat startup.
        local_only = model_cache.exists() and any(model_cache.glob("snapshots/*"))
        return SentenceTransformer(
            self.config.embedding_model,
            device=device,
            cache_folder=str(cache_root),
            local_files_only=local_only,
        )

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        lengths = self.model.tokenizer(texts, truncation=False, padding=False,
                                       return_length=True, verbose=False)["length"]
        if any(length > self.model.max_seq_length for length in lengths):
            raise ValueError("Embedding input exceeds the model token window. Rechunk before building; silent truncation is disabled.")
        return self.model.encode(
            texts,
            batch_size=self.config.embedding_batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

    def encode_query(self, question: str) -> np.ndarray:
        vector = self.model.encode(
            [BGE_QUERY_PREFIX + question.strip()],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vector.astype("float32")[0]
