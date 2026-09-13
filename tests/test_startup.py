"""Ensure optional AI libraries cannot delay model-free backend startup."""

import os
import subprocess
import sys
from pathlib import Path


def test_backend_import_does_not_import_local_model_libraries():
    code = """
import importlib.abc
import sys
class BlockHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers', 'sentence_transformers', 'huggingface_hub'}:
            raise AssertionError('Eager AI import: ' + fullname)
sys.meta_path.insert(0, BlockHeavyImports())
from src.runtime import load_pipeline
from src.llm import GeminiLLM
from config import settings
assert isinstance(GeminiLLM(settings), GeminiLLM)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            env=os.environ.copy(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
