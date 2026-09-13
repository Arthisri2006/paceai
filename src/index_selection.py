"""Atomic selection of an immutable local candidate; legacy index is rollback."""
from __future__ import annotations

import hashlib
from pathlib import Path

from config import Settings, settings
from src.utils import load_json, save_json

FILES = ("vectors.faiss", "vector_records.json", "bm25_corpus.json", "status.json")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def selection(config: Settings = settings) -> tuple[str, tuple]:
    root = config.index_dir.resolve()
    marker = load_json(root / "active.json", {"path": "."})
    if not isinstance(marker, dict):
        raise ValueError("Invalid active-index selection.")
    name = marker.get("path")
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError("Invalid active-index selection.")
    path = (root / name).resolve()
    if path == root and name == ".":
        return str(root), ()
    if not path.is_relative_to((root.parent / "candidates").resolve()):
        raise ValueError("Active index must be a local candidate directory.")
    hashes = marker.get("sha256", {})
    if not isinstance(hashes, dict) or set(hashes) != set(FILES) or not all(isinstance(hashes[x], str) and len(hashes[x]) == 64 for x in FILES):
        raise ValueError("Active index is missing its integrity manifest.")
    return str(path), tuple((name, hashes[name]) for name in FILES)


def verify_selection(selected: tuple[str, tuple]) -> None:
    path, hashes = selected
    for filename, expected in hashes:
        if digest(Path(path) / filename) != expected:
            raise ValueError("Selected index failed integrity verification. Restore the previous snapshot.")


def activate(candidate: Path, config: Settings = settings) -> None:
    root = config.index_dir.resolve()
    path = candidate.resolve()
    if not path.is_relative_to((root.parent / "candidates").resolve()):
        raise ValueError("Only a local candidate can be activated.")
    report = load_json(path / "evaluation.json", {})
    if not report.get("eligible_for_promotion") or report.get("new_oversized") != 0:
        raise ValueError("Candidate has not passed the retrieval/token safety gate.")
    hashes = {name: digest(path / name) for name in FILES}
    if hashes != report.get("tested_sha256"):
        raise ValueError("Candidate changed after evaluation. Rerun its safety gate.")
    # All large files are already complete. Only this small pointer is replaced.
    marker = {"path": "../candidates/" + path.relative_to(root.parent / "candidates").as_posix(),
              "sha256": hashes}
    save_json(root / "active.json", marker)


def rollback(config: Settings = settings) -> None:
    save_json(config.index_dir / "active.json", {"path": "."})
