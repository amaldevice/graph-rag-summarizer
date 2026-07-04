import os
from typing import Protocol

import boto3

from config.settings import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT_URL,
    MINIO_PUBLIC_BASE_URL,
    MINIO_SECRET_KEY,
)


class UploadClient(Protocol):
    def upload_file(self, filename: str, bucket: str, key: str) -> None: ...


class MinIOHandler:
    def __init__(
        self,
        endpoint_url: str = MINIO_ENDPOINT_URL,
        access_key: str = MINIO_ACCESS_KEY,
        secret_key: str = MINIO_SECRET_KEY,
        bucket: str = MINIO_BUCKET,
        public_base_url: str = MINIO_PUBLIC_BASE_URL,
        client: UploadClient | None = None,
    ) -> None:
        self.bucket_name = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
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
