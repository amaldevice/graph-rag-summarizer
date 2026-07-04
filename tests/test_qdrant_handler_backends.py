import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from vectordb.qdrant_handler import QdrantHandler


def test_qdrant_handler_uses_cloud_backend_when_requested(monkeypatch) -> None:
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", fake_client)

    QdrantHandler(
        qdrant_backend="cloud",
        qdrant_url="https://example.qdrant.io",
        qdrant_api_key="secret",
    )

    assert captured == {
        "url": "https://example.qdrant.io",
        "api_key": "secret",
        "timeout": 60,
    }


def test_qdrant_handler_uses_local_backend_when_requested(monkeypatch) -> None:
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", fake_client)

    QdrantHandler(
        qdrant_backend="local",
        qdrant_host="localhost",
        qdrant_port=6333,
    )

    assert captured == {
        "host": "localhost",
        "port": 6333,
    }


def test_qdrant_handler_uses_cloud_backend_in_auto_mode_when_url_exists(monkeypatch) -> None:
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", fake_client)

    QdrantHandler(
        qdrant_backend="auto",
        qdrant_url="https://example.qdrant.io",
        qdrant_api_key="secret",
    )

    assert captured["url"] == "https://example.qdrant.io"
    assert captured["api_key"] == "secret"


def test_qdrant_handler_uses_local_backend_in_auto_mode_without_url(monkeypatch) -> None:
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", fake_client)

    QdrantHandler(
        qdrant_backend="auto",
        qdrant_url="",
        qdrant_host="localhost",
        qdrant_port=6333,
    )

    assert captured == {
        "host": "localhost",
        "port": 6333,
    }


def test_qdrant_handler_rejects_cloud_backend_without_url() -> None:
    with pytest.raises(ValueError, match="QDRANT_URL is required"):
        QdrantHandler(qdrant_backend="cloud", qdrant_url="")


def test_qdrant_handler_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported Qdrant backend"):
        QdrantHandler(qdrant_backend="invalid")
