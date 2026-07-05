import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.check_cloud_connections import (
    check_qdrant_connection,
    check_r2_connection,
    get_missing_env_vars,
)


def test_get_missing_env_vars_reports_only_empty_values(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)

    missing = get_missing_env_vars(("QDRANT_URL", "QDRANT_API_KEY"))

    assert missing == ["QDRANT_API_KEY"]


def test_check_qdrant_connection_uses_cloud_handler(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    monkeypatch.setenv("QDRANT_COLLECTION", "demo")

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(
                collections=[
                    SimpleNamespace(name="demo"),
                    SimpleNamespace(name="archive"),
                ]
            )

    class FakeHandler:
        def __init__(self, qdrant_backend=None):
            assert qdrant_backend == "cloud"
            self.client = FakeClient()

    result = check_qdrant_connection(handler_cls=FakeHandler)

    assert result == {
        "collection_target": "demo",
        "collections": ["demo", "archive"],
    }


def test_check_r2_connection_heads_the_bucket(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "bucket-name")
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.com")

    called = {}

    class FakeClient:
        def head_bucket(self, Bucket):
            called["bucket"] = Bucket

    class FakeHandler:
        def __init__(self):
            self.bucket_name = "bucket-name"
            self.public_base_url = "https://cdn.example.com"
            self.client = FakeClient()

    result = check_r2_connection(handler_cls=FakeHandler)

    assert called == {"bucket": "bucket-name"}
    assert result == {
        "bucket": "bucket-name",
        "public_base_url": "https://cdn.example.com",
    }
