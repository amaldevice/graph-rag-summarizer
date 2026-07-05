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
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        public_base_url: str | None = None,
        client: UploadClient | None = None,
    ) -> None:
        endpoint_url = endpoint_url or os.getenv("MINIO_ENDPOINT_URL", MINIO_ENDPOINT_URL)
        access_key = access_key or os.getenv("MINIO_ACCESS_KEY", MINIO_ACCESS_KEY)
        secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", MINIO_SECRET_KEY)
        bucket = bucket or os.getenv("MINIO_BUCKET", MINIO_BUCKET)
        public_base_url = public_base_url or os.getenv("MINIO_PUBLIC_BASE_URL", MINIO_PUBLIC_BASE_URL)
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
