from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    current_dir = Path(__file__).resolve().parent
    for candidate in (current_dir, *current_dir.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return current_dir.parent


def get_embedding_cache_root(project_root: Path | None = None) -> Path:
    cache_root = (project_root or get_project_root()) / ".cache" / "embedding"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def get_sentence_transformers_cache_dir(project_root: Path | None = None) -> Path:
    cache_dir = get_embedding_cache_root(project_root) / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_onnx_cache_dir(project_root: Path | None = None) -> Path:
    cache_dir = get_embedding_cache_root(project_root) / "onnx"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
