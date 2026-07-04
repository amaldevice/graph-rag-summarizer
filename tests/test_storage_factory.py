import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from storage.factory import get_storage_handler


def test_get_storage_handler_returns_r2_when_backend_is_r2(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr("storage.factory.R2Handler", lambda: sentinel)

    assert get_storage_handler("r2") is sentinel


def test_get_storage_handler_returns_minio_when_backend_is_minio(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr("storage.factory.MinIOHandler", lambda: sentinel)

    assert get_storage_handler("minio") is sentinel


def test_get_storage_handler_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported storage backend"):
        get_storage_handler("invalid")
