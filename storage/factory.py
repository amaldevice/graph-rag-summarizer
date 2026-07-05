import os

from config.settings import STORAGE_BACKEND
from storage.minio_handler import MinIOHandler
from storage.r2_handler import R2Handler


def get_storage_handler(backend: str | None = None):
    backend = (backend or os.getenv("STORAGE_BACKEND", STORAGE_BACKEND)).lower()
    if backend == "r2":
        return R2Handler()
    if backend == "minio":
        return MinIOHandler()
    raise ValueError(f"Unsupported storage backend: {backend}")
