import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.r2_handler import R2Handler


def test_build_image_url_uses_public_base_and_object_name() -> None:
    handler = R2Handler(
        account_id="acct",
        access_key_id="key",
        secret_access_key="secret",
        bucket="bucket",
        public_base_url="https://pub.example.r2.dev",
    )

    assert handler.build_image_url("images/page-1.png") == "https://pub.example.r2.dev/images/page-1.png"


def test_upload_local_path_uses_provided_key() -> None:
    captured: dict[str, str] = {}

    class FakeClient:
        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            captured["filename"] = filename
            captured["bucket"] = bucket
            captured["key"] = key

    handler = R2Handler(
        account_id="acct",
        access_key_id="key",
        secret_access_key="secret",
        bucket="bucket",
        public_base_url="https://pub.example.r2.dev",
        client=FakeClient(),
    )

    object_name = handler.upload_local_path("/tmp/page-1.png", object_name="images/page-1.png")

    assert object_name == "images/page-1.png"
    assert captured == {
        "filename": "/tmp/page-1.png",
        "bucket": "bucket",
        "key": "images/page-1.png",
    }
