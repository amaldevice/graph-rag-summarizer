import os
from typing import Protocol

import boto3

from config.settings import (
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET,
    R2_PUBLIC_BASE_URL,
    R2_SECRET_ACCESS_KEY,
)


class UploadClient(Protocol):
    def upload_file(self, filename: str, bucket: str, key: str) -> None: ...


class R2Handler:
    def __init__(
        self,
        account_id: str = R2_ACCOUNT_ID,
        access_key_id: str = R2_ACCESS_KEY_ID,
        secret_access_key: str = R2_SECRET_ACCESS_KEY,
        bucket: str = R2_BUCKET,
        public_base_url: str = R2_PUBLIC_BASE_URL,
        client: UploadClient | None = None,
    ) -> None:
        self.bucket_name = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = client or boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def upload_local_path(
        self,
        file_path: str,
        object_name: str | None = None,
        content_type: str = "image/png",
    ) -> str:
        del content_type
        key = object_name or os.path.basename(file_path)
        self.client.upload_file(file_path, self.bucket_name, key)
        return key

    def build_image_url(self, object_name: str) -> str:
        return f"{self.public_base_url}/{object_name.lstrip('/')}"
