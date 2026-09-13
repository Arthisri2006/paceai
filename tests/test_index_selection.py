from dataclasses import replace
from pathlib import Path

import pytest

from config import settings
from src.index_selection import FILES, activate, rollback, selection, verify_selection, digest
from src.utils import save_json


def candidate(tmp_path):
    config = replace(settings, index_dir=tmp_path / "index")
    config.index_dir.mkdir()
    path = tmp_path / "candidates" / "tested"
    path.mkdir(parents=True)
    for filename in FILES:
        (path / filename).write_text("test fixture", encoding="utf-8")
    save_json(path / "evaluation.json", {"eligible_for_promotion": True, "new_oversized": 0,
                                        "tested_sha256": {name: digest(path / name) for name in FILES}})
    return config, path


def test_atomic_selection_and_non_destructive_rollback(tmp_path):
    config, path = candidate(tmp_path)
    original = selection(config)
    activate(path, config)
    selected = selection(config)
    assert selected != original and Path(selected[0]) == path
    verify_selection(selected)
    rollback(config)
    assert selection(config) == original
    assert all((path / name).exists() for name in FILES)


def test_corruption_or_failed_quality_gate_rejected(tmp_path):
    config, path = candidate(tmp_path)
    activate(path, config)
    selected = selection(config)
    (path / FILES[0]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        verify_selection(selected)
    with pytest.raises(ValueError, match="changed after evaluation"):
        activate(path, config)
    save_json(path / "evaluation.json", {"eligible_for_promotion": False, "new_oversized": 0})
    with pytest.raises(ValueError, match="gate"):
        activate(path, config)


def test_selection_cannot_escape_candidate_directory(tmp_path):
    config, _ = candidate(tmp_path)
    save_json(config.index_dir / "active.json", {"path": "../../outside"})
    with pytest.raises(ValueError, match="local candidate"):
        selection(config)
    with pytest.raises(ValueError, match="local candidate"):
        activate(tmp_path.parent, config)


def test_incomplete_candidate_never_replaces_marker(tmp_path):
    config, path = candidate(tmp_path)
    rollback(config)
    before = (config.index_dir / "active.json").read_bytes()
    (path / FILES[0]).unlink()
    with pytest.raises(FileNotFoundError):
        activate(path, config)
    assert (config.index_dir / "active.json").read_bytes() == before
