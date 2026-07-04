import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.minio_handler import MinIOHandler


def test_build_image_url_uses_public_base_and_object_name() -> None:
    handler = MinIOHandler(
        endpoint_url="http://localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        bucket="summarizer-images",
        public_base_url="http://localhost:9000/summarizer-images",
    )

    assert (
        handler.build_image_url("images/doc/page-1.png")
        == "http://localhost:9000/summarizer-images/images/doc/page-1.png"
    )


def test_upload_local_path_uses_bucket_and_key() -> None:
    captured: dict[str, str] = {}

    class FakeClient:
        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            captured["filename"] = filename
            captured["bucket"] = bucket
            captured["key"] = key

    handler = MinIOHandler(
        endpoint_url="http://localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        bucket="summarizer-images",
        public_base_url="http://localhost:9000/summarizer-images",
        client=FakeClient(),
    )

    object_name = handler.upload_local_path(
        "/tmp/page-1.png",
        object_name="images/doc/page-1.png",
    )

    assert object_name == "images/doc/page-1.png"
    assert captured == {
        "filename": "/tmp/page-1.png",
        "bucket": "summarizer-images",
        "key": "images/doc/page-1.png",
    }
