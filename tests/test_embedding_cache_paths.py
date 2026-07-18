import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from embedding.cache_paths import (
    get_embedding_cache_root,
    get_onnx_cache_dir,
    get_sentence_transformers_cache_dir,
)


def test_embedding_cache_root_is_project_local(tmp_path: Path) -> None:
    cache_root = get_embedding_cache_root(tmp_path)

    assert cache_root == tmp_path / ".cache" / "embedding"
    assert cache_root.is_dir()


def test_embedding_cache_root_uses_explicit_runtime_mount(monkeypatch, tmp_path: Path) -> None:
    mounted_cache = tmp_path / "mounted-cache"
    monkeypatch.setenv("EMBEDDING_CACHE_ROOT", str(mounted_cache))

    cache_root = get_embedding_cache_root()

    assert cache_root == mounted_cache
    assert cache_root.is_dir()


def test_sentence_transformers_cache_dir_is_nested_under_embedding_cache(tmp_path: Path) -> None:
    cache_dir = get_sentence_transformers_cache_dir(tmp_path)

    assert cache_dir == tmp_path / ".cache" / "embedding" / "models"
    assert cache_dir.is_dir()


def test_onnx_cache_dir_is_nested_under_embedding_cache(tmp_path: Path) -> None:
    cache_dir = get_onnx_cache_dir(tmp_path)

    assert cache_dir == tmp_path / ".cache" / "embedding" / "onnx"
    assert cache_dir.is_dir()
