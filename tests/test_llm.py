"""Fast unit tests for local-model cache behavior."""

from pathlib import Path

from src.llm import _has_cached_model_weights


def test_tokenizer_only_cache_is_not_treated_as_complete(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")

    assert not _has_cached_model_weights(tmp_path)


def test_safetensors_cache_is_complete(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"weights")

    assert _has_cached_model_weights(tmp_path)
