# Dual Local/Cloud Storage and Qdrant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `summarizer_project` run the same graph-rag-style ingest flow against either `R2 + Qdrant Cloud` or `MinIO + local Qdrant`, with the switch controlled by environment variables and with no change to the post-retrieval summarization pipeline.

**Architecture:** Keep the current graph-rag ingest merge, but replace hardcoded backend assumptions with one small storage factory and one explicit Qdrant mode selector. `DoclingLoader` becomes backend-neutral, `docker-compose.yml` becomes useful again for local mode, and the downstream chunk contract stays unchanged so `main.py`, `graph/*`, and `summarizer/*` do not need to move.

**Tech Stack:** Python, Docling, boto3/botocore, Qdrant, Docker Compose, Cloudflare R2, MinIO, pytest, Google Colab CLI

---

**Execution Environment Constraint:** Repository rules say Python code should not be run locally. All Python verification commands below are written to run through Colab CLI, except Docker-only infrastructure checks which use `docker compose`.

## File Structure

### Create

- `summarizer_project/scripts/run_targeted_pytest.py` — tiny Colab-safe pytest launcher.
- `summarizer_project/storage/base.py` — shared storage contract.
- `summarizer_project/storage/factory.py` — returns the active storage backend.
- `summarizer_project/storage/minio_handler.py` — local S3-compatible object-storage backend.
- `summarizer_project/tests/test_storage_factory.py` — backend selector tests.
- `summarizer_project/tests/test_minio_handler.py` — MinIO URL/upload tests.
- `summarizer_project/tests/test_docling_loader_storage_contract.py` — Docling loader contract tests against the shared storage interface.
- `summarizer_project/tests/test_qdrant_handler_backends.py` — local/cloud/auto Qdrant tests.
- `summarizer_project/docker/minio/init-bucket.sh` — local bucket bootstrap helper.

### Modify

- `summarizer_project/config/settings.py` — add explicit storage and Qdrant backend selectors plus MinIO config.
- `summarizer_project/env.example` — document cloud profile and local Docker profile.
- `summarizer_project/storage/r2_handler.py` — keep contract aligned with the shared interface.
- `summarizer_project/preprocessing/docling_loader.py` — use the storage factory instead of a hardwired `R2Handler`.
- `summarizer_project/vectordb/qdrant_handler.py` — support `QDRANT_BACKEND=auto|cloud|local`.
- `summarizer_project/docker-compose.yml` — re-enable local MinIO usage and bucket bootstrap.
- `summarizer_project/test_database/qdrant_r2_test.py` — rename behavior/output to backend-neutral wording or replace with backend-neutral equivalent.
- `summarizer_project/README.md` — document local/cloud modes and clarify that the downstream summarizer flow is unchanged.

### Keep unchanged in this plan

- `summarizer_project/main.py`
- `summarizer_project/graph/*`
- `summarizer_project/summarizer/*`
- `summarizer_project/evaluation/*`
- `summarizer_project/pipeline/feedback_loop.py`
- `summarizer_project/embedding/embedder.py`

---

### Task 1: Add a Colab-safe pytest launcher for `summarizer_project`

**Files:**
- Create: `summarizer_project/scripts/run_targeted_pytest.py`

- [ ] **Step 1: Write the tiny pytest launcher**

```python
# summarizer_project/scripts/run_targeted_pytest.py
import sys

import pytest


def main() -> int:
    args = sys.argv[1:] or ["summarizer_project/tests", "-v"]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the launcher against tests that already exist**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_r2_handler.py summarizer_project/tests/test_qdrant_handler_cloud.py -v
```

Expected: PASS, proving that the repo can run targeted pytest checks through Colab CLI without local Python.

- [ ] **Step 3: Commit**

```bash
git add summarizer_project/scripts/run_targeted_pytest.py
git commit -m $'Make Colab the standard verification path for summarizer_project tests\n\nConstraint: Repository rules disallow local Python execution for project code\nRejected: Run pytest directly on the host machine | Violates repo execution rules\nConfidence: high\nScope-risk: narrow\nDirective: Reuse this launcher for later targeted test steps\nTested: colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_r2_handler.py summarizer_project/tests/test_qdrant_handler_cloud.py -v\nNot-tested: local host pytest execution by design'
```

### Task 2: Introduce backend-neutral object storage selection

**Files:**
- Create: `summarizer_project/storage/base.py`
- Create: `summarizer_project/storage/factory.py`
- Create: `summarizer_project/storage/minio_handler.py`
- Create: `summarizer_project/tests/test_storage_factory.py`
- Create: `summarizer_project/tests/test_minio_handler.py`
- Modify: `summarizer_project/storage/r2_handler.py`
- Modify: `summarizer_project/config/settings.py`
- Modify: `summarizer_project/env.example`

- [ ] **Step 1: Write the failing storage selection tests**

```python
# summarizer_project/tests/test_storage_factory.py
import pytest

from storage.factory import get_storage_handler
from storage.minio_handler import MinIOHandler
from storage.r2_handler import R2Handler


def test_get_storage_handler_returns_r2_when_backend_is_r2(monkeypatch) -> None:
    monkeypatch.setattr("storage.factory.STORAGE_BACKEND", "r2")
    handler = get_storage_handler()
    assert isinstance(handler, R2Handler)


def test_get_storage_handler_returns_minio_when_backend_is_minio(monkeypatch) -> None:
    monkeypatch.setattr("storage.factory.STORAGE_BACKEND", "minio")
    handler = get_storage_handler()
    assert isinstance(handler, MinIOHandler)


def test_get_storage_handler_rejects_unknown_backend(monkeypatch) -> None:
    monkeypatch.setattr("storage.factory.STORAGE_BACKEND", "invalid")
    with pytest.raises(ValueError, match="Unsupported storage backend"):
        get_storage_handler()
```

```python
# summarizer_project/tests/test_minio_handler.py
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
```

- [ ] **Step 2: Run the storage tests to verify they fail**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py -v
```

Expected: FAIL because `storage.factory` and `storage.minio_handler` do not exist yet.

- [ ] **Step 3: Add the explicit backend selector settings**

```python
# summarizer_project/config/settings.py
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "r2").lower()

QDRANT_BACKEND = os.getenv("QDRANT_BACKEND", "auto").lower()
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "summarizer_docs")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "")

MINIO_ENDPOINT_URL = os.getenv("MINIO_ENDPOINT_URL", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "summarizer-images")
MINIO_PUBLIC_BASE_URL = os.getenv(
    "MINIO_PUBLIC_BASE_URL",
    "http://localhost:9000/summarizer-images",
)
```

```env
# summarizer_project/env.example
STORAGE_BACKEND=r2

QDRANT_BACKEND=cloud
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=replace_me
QDRANT_COLLECTION=summarizer_docs

R2_ACCOUNT_ID=replace_me
R2_ACCESS_KEY_ID=replace_me
R2_SECRET_ACCESS_KEY=replace_me
R2_BUCKET=replace_me
R2_PUBLIC_BASE_URL=https://pub-example.r2.dev

MINIO_ENDPOINT_URL=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=summarizer-images
MINIO_PUBLIC_BASE_URL=http://localhost:9000/summarizer-images
```

- [ ] **Step 4: Implement the shared storage contract, MinIO backend, and factory**

```python
# summarizer_project/storage/base.py
from typing import Protocol


class ObjectStorage(Protocol):
    def upload_local_path(
        self,
        file_path: str,
        object_name: str | None = None,
        content_type: str = "image/png",
    ) -> str: ...

    def build_image_url(self, object_name: str) -> str: ...
```

```python
# summarizer_project/storage/minio_handler.py
import os
from typing import Protocol

import boto3
from botocore.config import Config

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
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
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
```

```python
# summarizer_project/storage/factory.py
from config.settings import STORAGE_BACKEND
from storage.minio_handler import MinIOHandler
from storage.r2_handler import R2Handler


def get_storage_handler():
    if STORAGE_BACKEND == "r2":
        return R2Handler()
    if STORAGE_BACKEND == "minio":
        return MinIOHandler()
    raise ValueError(f"Unsupported storage backend: {STORAGE_BACKEND}")
```

```python
# summarizer_project/storage/r2_handler.py
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
```

- [ ] **Step 5: Run the storage tests to verify they pass**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py summarizer_project/tests/test_r2_handler.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add summarizer_project/storage/base.py summarizer_project/storage/factory.py summarizer_project/storage/minio_handler.py summarizer_project/storage/r2_handler.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py summarizer_project/config/settings.py summarizer_project/env.example
git commit -m $'Allow ingest storage to switch between R2 and MinIO without code edits\n\nConstraint: The same ingest path must support Colab/cloud and Docker/local usage\nRejected: Keep R2 hardcoded in DoclingLoader | Makes MinIO docker stack useless\nConfidence: high\nScope-risk: moderate\nDirective: Keep the shared storage contract minimal and downstream-agnostic\nTested: colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py summarizer_project/tests/test_r2_handler.py -v\nNot-tested: live MinIO upload against local docker services'
```

### Task 3: Rewire `DoclingLoader` to use the shared storage backend

**Files:**
- Modify: `summarizer_project/preprocessing/docling_loader.py`
- Create: `summarizer_project/tests/test_docling_loader_storage_contract.py`

- [ ] **Step 1: Write the failing Docling loader storage contract tests**

```python
# summarizer_project/tests/test_docling_loader_storage_contract.py
from preprocessing.docling_loader import DoclingLoader


def test_upload_exported_images_uses_backend_neutral_handler() -> None:
    loader = DoclingLoader.__new__(DoclingLoader)

    class FakeStorage:
        def upload_local_path(self, file_path: str, object_name: str | None = None, content_type: str = "image/png") -> str:
            return object_name or ""

        def build_image_url(self, object_name: str) -> str:
            return f"https://assets.example/{object_name}"

    loader.storage_handler = FakeStorage()

    uploaded = loader._upload_exported_images(
        [{"type": "page", "page": 2, "path": "/tmp/page-2.png"}],
        "sample",
    )

    assert uploaded == [{
        "type": "page",
        "page": 2,
        "object_name": "images/sample/page-2.png",
        "image_url": "https://assets.example/images/sample/page-2.png",
    }]


def test_attach_image_urls_to_chunks_keeps_downstream_contract() -> None:
    loader = DoclingLoader.__new__(DoclingLoader)
    chunks = [{"chunk_id": 1, "page_no": 4, "image_url": None}]

    attached = loader.attach_image_urls_to_chunks(
        chunks,
        {4: "https://assets.example/images/sample/page-4.png"},
    )

    assert attached == [{
        "chunk_id": 1,
        "page_no": 4,
        "image_url": "https://assets.example/images/sample/page-4.png",
    }]
```

- [ ] **Step 2: Run the Docling loader tests to verify they fail or expose the current R2 coupling**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_docling_loader_storage_contract.py -v
```

Expected: FAIL until `DoclingLoader` stops depending on a field named and constructed as R2-specific.

- [ ] **Step 3: Replace the hardwired R2 dependency with the storage factory**

```python
# summarizer_project/preprocessing/docling_loader.py
import os
from pathlib import Path

from docling.document_converter import DocumentConverter

from config import settings
from preprocessing.image_exporter import DoclingImageExporter
from storage.factory import get_storage_handler


class DoclingLoader:
    def __init__(self):
        self.converter = DocumentConverter()
        self.storage_handler = get_storage_handler()
        self.image_exporter = DoclingImageExporter()

    def _upload_exported_images(self, exported: list, doc_filename: str):
        uploaded = []
        for item in exported:
            object_name = f"images/{doc_filename}/{Path(item['path']).name}"
            self.storage_handler.upload_local_path(item["path"], object_name=object_name)
            image_url = self.storage_handler.build_image_url(object_name)
            uploaded.append({
                "type": item["type"],
                "page": item["page"],
                "object_name": object_name,
                "image_url": image_url,
            })
        return uploaded
```

- [ ] **Step 4: Keep the chunk payload shape unchanged**

```python
# summarizer_project/preprocessing/docling_loader.py
chunks.append({
    "chunk_id": chunk_id,
    "text": text.strip(),
    "level": type(element).__name__,
    "source": source_name,
    "page_no": page_no,
    "image_url": None,
})
```

- [ ] **Step 5: Run the Docling loader tests to verify they pass**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_docling_loader_storage_contract.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add summarizer_project/preprocessing/docling_loader.py summarizer_project/tests/test_docling_loader_storage_contract.py
git commit -m $'Decouple Docling ingest from a single storage provider\n\nConstraint: Local and cloud modes must share one ingest code path\nRejected: Add separate Docling loaders for MinIO and R2 | Duplicates ingest logic and risks contract drift\nConfidence: high\nScope-risk: narrow\nDirective: Keep image upload concerns behind the storage handler boundary\nTested: colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_docling_loader_storage_contract.py -v\nNot-tested: live image export upload against configured providers'
```

### Task 4: Make `QdrantHandler` support explicit `auto|cloud|local` selection

**Files:**
- Modify: `summarizer_project/vectordb/qdrant_handler.py`
- Create: `summarizer_project/tests/test_qdrant_handler_backends.py`
- Remove or leave superseded: `summarizer_project/tests/test_qdrant_handler_cloud.py`

- [ ] **Step 1: Write the failing Qdrant backend tests**

```python
# summarizer_project/tests/test_qdrant_handler_backends.py
from vectordb.qdrant_handler import QdrantHandler


def test_init_uses_cloud_client_when_backend_is_cloud(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", FakeClient)

    QdrantHandler(
        qdrant_backend="cloud",
        qdrant_url="https://cluster.qdrant.io",
        qdrant_api_key="secret",
    )

    assert captured == {
        "url": "https://cluster.qdrant.io",
        "api_key": "secret",
        "timeout": 60,
    }


def test_init_uses_local_client_when_backend_is_local(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", FakeClient)

    QdrantHandler(
        qdrant_backend="local",
        qdrant_host="localhost",
        qdrant_port=6333,
    )

    assert captured == {
        "host": "localhost",
        "port": 6333,
    }


def test_search_as_chunks_preserves_downstream_contract() -> None:
    class FakeResult:
        def __init__(self) -> None:
            self.id = 7
            self.score = 0.91
            self.payload = {
                "chunk_id": 7,
                "text": "hello",
                "level": "paragraph",
                "source": "docling",
                "page": 3,
                "image_urls": ["https://assets.example/page-3.png"],
            }

    handler = QdrantHandler.__new__(QdrantHandler)
    handler.search = lambda query_vector, limit=5: [FakeResult()]

    chunks = handler.search_as_chunks([0.1, 0.2], limit=1)

    assert chunks == [{
        "chunk_id": 7,
        "text": "hello",
        "level": "paragraph",
        "source": "docling",
        "page_no": 3,
        "image_url": "https://assets.example/page-3.png",
        "score": 0.91,
        "rank": 1,
    }]
```

- [ ] **Step 2: Run the Qdrant tests to verify they fail**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_qdrant_handler_backends.py -v
```

Expected: FAIL because `QdrantHandler` does not yet accept an explicit `qdrant_backend` selector.

- [ ] **Step 3: Add explicit backend selection while preserving `auto` behavior**

```python
# summarizer_project/vectordb/qdrant_handler.py
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config.settings import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_BACKEND,
    QDRANT_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_URL,
)


class QdrantHandler:
    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str = QDRANT_COLLECTION,
        qdrant_backend: str = QDRANT_BACKEND,
        qdrant_url: str = QDRANT_URL,
        qdrant_api_key: str = QDRANT_API_KEY,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
    ):
        backend = (qdrant_backend or "auto").lower()

        if client is not None:
            self.client = client
        elif backend == "cloud":
            self.client = QdrantClient(
                url=qdrant_url,
                api_key=qdrant_api_key or None,
                timeout=60,
            )
        elif backend == "local":
            self.client = QdrantClient(host=qdrant_host, port=qdrant_port)
        elif qdrant_url:
            self.client = QdrantClient(
                url=qdrant_url,
                api_key=qdrant_api_key or None,
                timeout=60,
            )
        else:
            self.client = QdrantClient(host=qdrant_host, port=qdrant_port)

        self.collection_name = collection_name
```

- [ ] **Step 4: Keep retrieval normalization unchanged**

```python
# summarizer_project/vectordb/qdrant_handler.py
def _normalize_chunk_payload(self, payload: dict, fallback_chunk_id, score=None, rank=None):
    chunk_id = payload.get("chunk_id", fallback_chunk_id)
    try:
        chunk_id = int(chunk_id)
    except (TypeError, ValueError):
        pass

    page_no = payload.get("page_no", payload.get("page"))
    image_url = payload.get("image_url")
    if image_url is None:
        image_urls = payload.get("image_urls") or []
        if image_urls:
            image_url = image_urls[0]

    return {
        "chunk_id": chunk_id,
        "text": payload.get("text", ""),
        "level": payload.get("level", "paragraph"),
        "source": payload.get("source", "docling"),
        "page_no": page_no,
        "image_url": image_url,
        "score": score,
        "rank": rank,
    }
```

- [ ] **Step 5: Run the Qdrant backend tests to verify they pass**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_qdrant_handler_backends.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add summarizer_project/vectordb/qdrant_handler.py summarizer_project/tests/test_qdrant_handler_backends.py summarizer_project/config/settings.py
git commit -m $'Make Qdrant mode explicit without breaking the retrieval contract\n\nConstraint: Cloud and local vector storage must use one handler and one payload shape\nRejected: Split cloud and local handlers | Creates unnecessary duplicate code paths\nConfidence: high\nScope-risk: narrow\nDirective: Preserve page_no and image_url normalization at the retrieval boundary\nTested: colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_qdrant_handler_backends.py -v\nNot-tested: live local Qdrant and cloud Qdrant in the same turn'
```

### Task 5: Restore `docker-compose.yml` as the supported local stack

**Files:**
- Modify: `summarizer_project/docker-compose.yml`
- Create: `summarizer_project/docker/minio/init-bucket.sh`

- [ ] **Step 1: Add a small MinIO bucket bootstrap script**

```bash
#!/bin/sh
set -eu

MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
  mc mb --ignore-existing "local/${MINIO_BUCKET}"
```

- [ ] **Step 2: Wire the init job into Docker Compose**

```yaml
# summarizer_project/docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant_local
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    container_name: minio_local
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    volumes:
      - minio_storage:/data
    command: server /data --console-address ":9001"
    restart: unless-stopped

  minio-create-bucket:
    image: minio/mc:latest
    depends_on:
      - minio
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
      MINIO_BUCKET: summarizer-images
    volumes:
      - ./docker/minio/init-bucket.sh:/init-bucket.sh:ro
    entrypoint: ["/bin/sh", "/init-bucket.sh"]
    restart: "no"

volumes:
  qdrant_storage:
  minio_storage:
```

- [ ] **Step 3: Validate the Compose file shape**

Run:

```bash
docker compose -f summarizer_project/docker-compose.yml config
```

Expected: output includes `minio-create-bucket` and no schema errors.

- [ ] **Step 4: Commit**

```bash
git add summarizer_project/docker-compose.yml summarizer_project/docker/minio/init-bucket.sh
git commit -m $'Make the local MinIO/Qdrant docker stack usable again\n\nConstraint: Local mode must be bootstrappable without hand-editing the codebase\nRejected: Keep docker-compose as documentation-only leftovers | Leaves local mode broken in practice\nConfidence: medium\nScope-risk: moderate\nDirective: Keep Docker bootstrap minimal and avoid adding app containers unless truly necessary\nTested: docker compose -f summarizer_project/docker-compose.yml config\nNot-tested: live docker startup and bucket creation in this planning-only change set'
```

### Task 6: Make docs and integration naming backend-neutral

**Files:**
- Modify or rename: `summarizer_project/test_database/qdrant_r2_test.py`
- Modify: `summarizer_project/README.md`

- [ ] **Step 1: Replace cloud-specific integration wording with backend-neutral wording**

```python
# summarizer_project/test_database/qdrant_r2_test.py
from config.settings import QDRANT_BACKEND, STORAGE_BACKEND

print("=== SUMMARIZER PROJECT STORAGE/QDRANT SMOKE TEST ===")
print(f"Storage backend : {STORAGE_BACKEND}")
print(f"Qdrant backend  : {QDRANT_BACKEND}")
```

```python
print("✅ Payload retrieved with text/page/image contract preserved")
```

- [ ] **Step 2: Document both supported runtime profiles in the README**

```markdown
## Backend Modes

### Cloud mode (default for Colab CLI)

- `STORAGE_BACKEND=r2`
- `QDRANT_BACKEND=cloud`
- uses Cloudflare R2 + Qdrant Cloud

### Local Docker mode

- `STORAGE_BACKEND=minio`
- `QDRANT_BACKEND=local`
- uses `summarizer_project/docker-compose.yml` for MinIO + local Qdrant

### Flow boundary

Everything up to Vector DB storage follows the graph-rag-style ingest merge.
Everything after retrieval from Vector DB remains in `summarizer_project`:

- entity extraction
- graph construction
- community detection
- graph analysis
- pruning / reranking
- prompt building
- LLM summarization
- hierarchical reduce
- evaluation
- quality gate
- feedback loop
```

- [ ] **Step 3: Run the final targeted regression suite**

Run:

```bash
colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_r2_handler.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py summarizer_project/tests/test_docling_loader_storage_contract.py summarizer_project/tests/test_qdrant_handler_backends.py -v
```

Expected: PASS.

- [ ] **Step 4: Re-validate Docker Compose**

Run:

```bash
docker compose -f summarizer_project/docker-compose.yml config
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add summarizer_project/test_database/qdrant_r2_test.py summarizer_project/README.md
git commit -m $'Document dual backend usage without changing downstream summarization flow\n\nConstraint: Operators need one clear story for cloud and local modes\nRejected: Leave docs cloud-only while re-adding MinIO support | Creates operator confusion and drift\nConfidence: high\nScope-risk: narrow\nDirective: Keep README ownership boundaries explicit around the Vector DB seam\nTested: colab run --gpu T4 summarizer_project/scripts/run_targeted_pytest.py summarizer_project/tests/test_r2_handler.py summarizer_project/tests/test_storage_factory.py summarizer_project/tests/test_minio_handler.py summarizer_project/tests/test_docling_loader_storage_contract.py summarizer_project/tests/test_qdrant_handler_backends.py -v; docker compose -f summarizer_project/docker-compose.yml config\nNot-tested: end-to-end local docker ingest smoke with live services'
```

---

## Self-Review

### Spec coverage

- Dual local/cloud storage support — covered by Tasks 2 and 3.
- Explicit Qdrant local/cloud selection — covered by Task 4.
- Restoring Docker usefulness — covered by Task 5.
- Keeping graph-rag ingest boundary and post-VectorDB ownership — reflected in Tasks 3, 4, and 6.
- Documentation and operator guidance — covered by Task 6.

No uncovered spec requirements remain.

### Placeholder scan

- No `TODO` or `TBD` placeholders remain.
- Each changed area includes exact file paths.
- Each verification step includes a concrete command and expected result.

### Type consistency

- Storage selector name is consistent: `STORAGE_BACKEND`.
- Qdrant selector name is consistent: `QDRANT_BACKEND`.
- Downstream payload fields remain consistent: `chunk_id`, `text`, `level`, `source`, `page_no`, `image_url`, `score`, `rank`.

## Execution Handoff

Plan complete and archived at `summarizer_project/docs/completed/superpowers/plans/2026-07-04-dual-local-cloud-storage-qdrant-implementation.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
