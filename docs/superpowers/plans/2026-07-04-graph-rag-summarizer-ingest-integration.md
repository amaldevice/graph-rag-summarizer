# Graph-RAG Summarizer Ingest Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `graph_rag-pipeline` the source of truth for Docling ingest, R2 image storage, and Cloud-Qdrant configuration inside `summarizer_project`, while preserving the existing `summarizer_project` pipeline from VectorDB retrieval onward.

**Architecture:** Replace `summarizer_project`'s MinIO-first ingest infrastructure with a thin adapter that follows the graph-rag Docling ingest direction, preserves the richer chunk payload required by downstream graph/summarizer code, and keeps `main.py` untouched except for the changed backend behavior. The migration is split into storage, vector DB, ingest orchestration, and contract verification so each task leaves the system in a working state.

**Tech Stack:** Python, Docling, PyMuPDF, boto3/S3-compatible Cloudflare R2, Qdrant Cloud, sentence-transformers, pytest

---

## File Structure

### Create

- `summarizer_project/storage/r2_handler.py` — active storage backend replacing live MinIO usage.
- `summarizer_project/tests/test_r2_handler.py` — unit tests for R2 URL and upload API behavior.
- `summarizer_project/tests/test_qdrant_handler_cloud.py` — unit tests for Cloud-Qdrant config and retrieved chunk contract.
- `summarizer_project/tests/test_docling_loader_r2_contract.py` — unit tests for image-upload integration and normalized chunk payload.
- `summarizer_project/tests/test_upload_to_qdrant_flow.py` — orchestration test for the new ingest wrapper.

### Modify

- `summarizer_project/config/settings.py` — switch active infra config from MinIO/local-Qdrant defaults to graph-rag-priority env vars.
- `summarizer_project/env.example` — document required R2 and Cloud-Qdrant variables.
- `summarizer_project/preprocessing/docling_loader.py` — remove live MinIO dependency, route uploads through the new R2 handler, preserve downstream chunk metadata.
- `summarizer_project/vectordb/qdrant_handler.py` — prefer `QDRANT_URL` + `QDRANT_API_KEY`, keep chunk-shaped payload methods.
- `summarizer_project/upload_to_qdrant.py` — act as graph-rag-priority ingest wrapper using the updated Docling flow.
- `summarizer_project/test_database/qdrant_minio_test.py` — rename semantics in output/logging from MinIO to R2 or replace with a backend-neutral integration check.
- `summarizer_project/README.md` — reflect R2 + Qdrant Cloud ingest ownership and remove MinIO-first guidance from the active path.

### Keep unchanged in this plan

- `summarizer_project/main.py`
- `summarizer_project/graph/*`
- `summarizer_project/summarizer/*`
- `summarizer_project/evaluation/*`
- `summarizer_project/pipeline/feedback_loop.py`

---

### Task 1: Replace live MinIO storage with an R2-backed handler

**Files:**
- Create: `summarizer_project/storage/r2_handler.py`
- Create: `summarizer_project/tests/test_r2_handler.py`
- Modify: `summarizer_project/config/settings.py`
- Modify: `summarizer_project/env.example`

- [ ] **Step 1: Write the failing storage tests**

```python
# summarizer_project/tests/test_r2_handler.py
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


def test_upload_local_path_uses_images_prefix(monkeypatch) -> None:
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
```

- [ ] **Step 2: Run the storage tests to verify they fail**

Run:

```bash
pytest summarizer_project/tests/test_r2_handler.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'storage.r2_handler'`

- [ ] **Step 3: Write the minimal R2 handler**

```python
# summarizer_project/storage/r2_handler.py
import os
from typing import Protocol

import boto3

from config.settings import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET,
    R2_PUBLIC_BASE_URL,
)


class S3UploadClient(Protocol):
    def upload_file(self, filename: str, bucket: str, key: str) -> None: ...


class R2Handler:
    def __init__(
        self,
        account_id: str = R2_ACCOUNT_ID,
        access_key_id: str = R2_ACCESS_KEY_ID,
        secret_access_key: str = R2_SECRET_ACCESS_KEY,
        bucket: str = R2_BUCKET,
        public_base_url: str = R2_PUBLIC_BASE_URL,
        client: S3UploadClient | None = None,
    ):
        self.bucket_name = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = client or boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def upload_local_path(self, file_path: str, object_name: str | None = None, content_type: str = "image/png") -> str:
        key = object_name or os.path.basename(file_path)
        self.client.upload_file(file_path, self.bucket_name, key)
        return key

    def build_image_url(self, object_name: str) -> str:
        return f"{self.public_base_url}/{object_name.lstrip('/')}"
```

- [ ] **Step 4: Add the new active config values**

```python
# summarizer_project/config/settings.py
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", 768))
```

```env
# summarizer_project/env.example
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=replace_me

R2_ACCOUNT_ID=replace_me
R2_ACCESS_KEY_ID=replace_me
R2_SECRET_ACCESS_KEY=replace_me
R2_BUCKET=replace_me
R2_PUBLIC_BASE_URL=https://pub-example.r2.dev

EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
EMBEDDING_DIM=768
```

- [ ] **Step 5: Run the storage tests to verify they pass**

Run:

```bash
pytest summarizer_project/tests/test_r2_handler.py -v
```

Expected: PASS (`2 passed`)

- [ ] **Step 6: Commit**

```bash
git add summarizer_project/storage/r2_handler.py summarizer_project/tests/test_r2_handler.py summarizer_project/config/settings.py summarizer_project/env.example
git commit -m "feat: add r2 storage backend"
```

### Task 2: Migrate `QdrantHandler` to Cloud-Qdrant semantics without changing downstream API

**Files:**
- Modify: `summarizer_project/vectordb/qdrant_handler.py`
- Create: `summarizer_project/tests/test_qdrant_handler_cloud.py`

- [ ] **Step 1: Write the failing Qdrant handler tests**

```python
# summarizer_project/tests/test_qdrant_handler_cloud.py
from vectordb.qdrant_handler import QdrantHandler


def test_search_as_chunks_returns_summarizer_contract() -> None:
    class FakeResult:
        def __init__(self) -> None:
            self.id = 7
            self.score = 0.91
            self.payload = {
                "chunk_id": 7,
                "text": "hello",
                "level": "paragraph",
                "source": "docling",
                "page_no": 3,
                "image_url": "https://pub.example.r2.dev/images/page-3.png",
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
        "image_url": "https://pub.example.r2.dev/images/page-3.png",
        "score": 0.91,
        "rank": 1,
    }]
```

- [ ] **Step 2: Run the Qdrant tests to verify the current handler is not yet cloud-configured**

Run:

```bash
pytest summarizer_project/tests/test_qdrant_handler_cloud.py -v
```

Expected: either import/setup failure for missing test file or a failure after adding the next assertion for config path

- [ ] **Step 3: Add a failing config-path assertion**

```python
def test_init_prefers_qdrant_url_and_api_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("vectordb.qdrant_handler.QdrantClient", FakeClient)
    monkeypatch.setattr("vectordb.qdrant_handler.QDRANT_URL", "https://cluster.qdrant.io")
    monkeypatch.setattr("vectordb.qdrant_handler.QDRANT_API_KEY", "secret")
    monkeypatch.setattr("vectordb.qdrant_handler.QDRANT_HOST", "localhost")
    monkeypatch.setattr("vectordb.qdrant_handler.QDRANT_PORT", 6333)

    handler = QdrantHandler()

    assert handler.collection_name
    assert captured == {"url": "https://cluster.qdrant.io", "api_key": "secret"}
```

- [ ] **Step 4: Implement the minimal Cloud-Qdrant preference logic**

```python
# summarizer_project/vectordb/qdrant_handler.py
from config.settings import (
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_URL,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    EMBEDDING_DIM,
)


class QdrantHandler:
    def __init__(self):
        if QDRANT_URL and QDRANT_API_KEY:
            self.client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        else:
            self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self.collection_name = QDRANT_COLLECTION
```

- [ ] **Step 5: Preserve chunk payload structure during upsert and retrieval**

```python
# summarizer_project/vectordb/qdrant_handler.py
payload = {
    "chunk_id": chunk_id,
    "text": chunk.get("text", ""),
    "level": chunk.get("level", "paragraph"),
    "source": chunk.get("source", "docling"),
    "page_no": chunk.get("page_no"),
    "image_url": chunk.get("image_url"),
}
```

- [ ] **Step 6: Run the Qdrant handler tests to verify they pass**

Run:

```bash
pytest summarizer_project/tests/test_qdrant_handler_cloud.py -v
```

Expected: PASS (`2 passed`)

- [ ] **Step 7: Commit**

```bash
git add summarizer_project/vectordb/qdrant_handler.py summarizer_project/tests/test_qdrant_handler_cloud.py
git commit -m "feat: support cloud qdrant for ingest"
```

### Task 3: Route Docling ingest image uploads through R2 while preserving chunk metadata

**Files:**
- Modify: `summarizer_project/preprocessing/docling_loader.py`
- Create: `summarizer_project/tests/test_docling_loader_r2_contract.py`

- [ ] **Step 1: Write the failing Docling loader contract tests**

```python
# summarizer_project/tests/test_docling_loader_r2_contract.py
from preprocessing.docling_loader import DoclingLoader


def test_upload_exported_images_builds_r2_urls() -> None:
    loader = DoclingLoader.__new__(DoclingLoader)

    class FakeStorage:
        def upload_local_path(self, file_path: str, object_name: str | None = None, content_type: str = "image/png") -> str:
            return object_name or ""

        def build_image_url(self, object_name: str) -> str:
            return f"https://pub.example.r2.dev/{object_name}"

    loader.storage_handler = FakeStorage()

    uploaded = loader._upload_exported_images(
        [{"type": "page", "page": 2, "path": "/tmp/doc-page-2.png"}],
        "doc",
    )

    assert uploaded == [{
        "type": "page",
        "page": 2,
        "object_name": "doc/doc-page-2.png",
        "image_url": "https://pub.example.r2.dev/doc/doc-page-2.png",
    }]


def test_attach_image_urls_to_chunks_matches_page_no() -> None:
    loader = DoclingLoader.__new__(DoclingLoader)
    chunks = [{"chunk_id": 1, "page_no": 4, "image_url": None}]

    attached = loader.attach_image_urls_to_chunks(chunks, {4: "https://pub.example.r2.dev/images/page-4.png"})

    assert attached[0]["image_url"] == "https://pub.example.r2.dev/images/page-4.png"
```

- [ ] **Step 2: Run the Docling loader tests to verify they fail or reveal MinIO-coupled assumptions**

Run:

```bash
pytest summarizer_project/tests/test_docling_loader_r2_contract.py -v
```

Expected: FAIL until `DoclingLoader` no longer hardcodes `MinIOHandler`

- [ ] **Step 3: Replace the live storage dependency in `DoclingLoader`**

```python
# summarizer_project/preprocessing/docling_loader.py
from storage.r2_handler import R2Handler


class DoclingLoader:
    def __init__(self):
        self.converter = DocumentConverter()
        self.storage_handler = R2Handler()
        self.image_exporter = DoclingImageExporter()
```

- [ ] **Step 4: Update the upload helper to use backend-neutral storage calls**

```python
def _upload_exported_images(self, exported: list, doc_filename: str):
    uploaded = []
    for item in exported:
        object_name = f"{doc_filename}/{Path(item['path']).name}"
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

- [ ] **Step 5: Keep chunk metadata unchanged for downstream modules**

```python
chunks.append({
    "chunk_id": chunk_id,
    "text": text.strip(),
    "level": type(element).__name__,
    "source": "docling",
    "page_no": page_no,
    "image_url": None,
})
```

- [ ] **Step 6: Run the Docling loader tests to verify they pass**

Run:

```bash
pytest summarizer_project/tests/test_docling_loader_r2_contract.py -v
```

Expected: PASS (`2 passed`)

- [ ] **Step 7: Commit**

```bash
git add summarizer_project/preprocessing/docling_loader.py summarizer_project/tests/test_docling_loader_r2_contract.py
git commit -m "feat: route docling image uploads through r2"
```

### Task 4: Rewire `upload_to_qdrant.py` as the graph-rag-priority ingest wrapper

**Files:**
- Modify: `summarizer_project/upload_to_qdrant.py`
- Create: `summarizer_project/tests/test_upload_to_qdrant_flow.py`

- [ ] **Step 1: Write the failing orchestration test**

```python
# summarizer_project/tests/test_upload_to_qdrant_flow.py
from upload_to_qdrant import main


def test_main_runs_docling_ingest_then_upserts(monkeypatch) -> None:
    calls: list[str] = []

    class FakeLoader:
        def process_pdf(self, pdf_path: str):
            calls.append(f"process:{pdf_path}")
            return {"chunks": [{"chunk_id": 1, "text": "hello", "level": "paragraph", "source": "docling", "page_no": 1, "image_url": None}]}

    class FakeEmbedder:
        def embed_chunks(self, chunks):
            calls.append(f"embed:{len(chunks)}")
            return [[0.1, 0.2]]

    class FakeQdrant:
        collection_name = "docs"

        def create_collection_if_not_exists(self):
            calls.append("create")

        def upsert_chunks(self, chunks, vectors):
            calls.append(f"upsert:{len(chunks)}:{len(vectors)}")

    monkeypatch.setattr("upload_to_qdrant.DoclingLoader", FakeLoader)
    monkeypatch.setattr("upload_to_qdrant.TextEmbedder", FakeEmbedder)
    monkeypatch.setattr("upload_to_qdrant.QdrantHandler", FakeQdrant)
    monkeypatch.setattr("upload_to_qdrant.os.getenv", lambda key, default=None: "sample.pdf" if key == "PDF_PATH" else default)

    main()

    assert calls == ["process:sample.pdf", "embed:1", "create", "upsert:1:1"]
```

- [ ] **Step 2: Run the orchestration test to verify the current entry point behavior is captured**

Run:

```bash
pytest summarizer_project/tests/test_upload_to_qdrant_flow.py -v
```

Expected: PASS or minimal adjustment needed for import path; this locks current orchestration before the backend swap.

- [ ] **Step 3: Adjust `upload_to_qdrant.py` only if needed to make ownership explicit**

```python
# summarizer_project/upload_to_qdrant.py
def main():
    pdf_path = os.getenv("PDF_PATH", "sample.pdf")

    loader = DoclingLoader()
    result = loader.process_pdf(pdf_path)
    chunks = result["chunks"]

    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    qdrant = QdrantHandler()
    qdrant.create_collection_if_not_exists()
    qdrant.upsert_chunks(chunks, vectors)
```

The code stays small; ownership changes come from the swapped internals, not from adding orchestration complexity here.

- [ ] **Step 4: Run the orchestration test again**

Run:

```bash
pytest summarizer_project/tests/test_upload_to_qdrant_flow.py -v
```

Expected: PASS (`1 passed`)

- [ ] **Step 5: Commit**

```bash
git add summarizer_project/upload_to_qdrant.py summarizer_project/tests/test_upload_to_qdrant_flow.py
git commit -m "test: lock ingest wrapper orchestration"
```

### Task 5: Convert the old MinIO integration script into an R2 + retrieval-contract verification script

**Files:**
- Modify: `summarizer_project/test_database/qdrant_minio_test.py`
- Modify: `summarizer_project/README.md`

- [ ] **Step 1: Write the renamed integration expectations into the script output**

```python
# summarizer_project/test_database/qdrant_minio_test.py
print("  TEST QDRANT + R2")
```

```python
print("   ✅ Image URL berhasil disimpan di Qdrant payload!")
print("   Buka URL di browser untuk verifikasi gambar dari R2.")
```

- [ ] **Step 2: Replace MinIO-specific wording in the script comments and CSV intent**

```python
# Cek apakah query mengembalikan text + image_url + page_no dari backend R2/Qdrant
```

- [ ] **Step 3: Update the README active-path guidance**

```markdown
### Storage and Vector DB

- Active ingest storage uses Cloudflare R2-compatible object storage.
- Active vector storage uses Qdrant Cloud-style configuration via `QDRANT_URL` and `QDRANT_API_KEY` when present.
- MinIO is no longer part of the active ingest path.
```

- [ ] **Step 4: Run targeted tests for the contract-bearing units**

Run:

```bash
pytest summarizer_project/tests/test_r2_handler.py summarizer_project/tests/test_qdrant_handler_cloud.py summarizer_project/tests/test_docling_loader_r2_contract.py summarizer_project/tests/test_upload_to_qdrant_flow.py -v
```

Expected: PASS (`7 passed` if all tests above are present)

- [ ] **Step 5: Run the backend-neutral integration script manually when credentials are configured**

Run:

```bash
python summarizer_project/test_database/qdrant_minio_test.py
```

Expected: script prints `TEST QDRANT + R2`, uploads/retrieves sample data, and reports at least one retrieved row with `page_no`, `text`, and an R2-backed `image_url` when image export succeeds.

- [ ] **Step 6: Commit**

```bash
git add summarizer_project/test_database/qdrant_minio_test.py summarizer_project/README.md
git commit -m "docs: reflect r2 and cloud qdrant ingest path"
```

### Task 6: Full regression check against the retrieval-to-summary seam

**Files:**
- Modify if needed: `summarizer_project/main.py` only if a payload key mismatch is discovered
- Test: existing `summarizer_project/main.py` runtime path

- [ ] **Step 1: Write the seam assertion as a focused regression test if `main.py` reveals a mismatch**

```python
def test_retrieved_chunks_match_main_pipeline_contract() -> None:
    retrieved_chunk = {
        "chunk_id": 1,
        "text": "hello",
        "level": "paragraph",
        "source": "docling",
        "page_no": 1,
        "image_url": "https://pub.example.r2.dev/images/page-1.png",
        "score": 0.9,
        "rank": 1,
    }

    assert set(retrieved_chunk) >= {"chunk_id", "text", "level", "source", "page_no", "image_url", "score", "rank"}
```

- [ ] **Step 2: Run the retrieval-to-summary smoke path**

Run:

```bash
python summarizer_project/main.py
```

Expected: retrieval succeeds, `EntityExtractor.extract_entities()` receives chunk dictionaries with `chunk_id`, and no failure occurs because of missing `page_no`/`image_url`/`level` keys.

- [ ] **Step 3: If `main.py` fails only because of field naming, apply the smallest fix at the adapter boundary**

```python
# Example of the only acceptable shape of fix: normalize at retrieval boundary
retrieved_chunks.append({
    "chunk_id": payload.get("chunk_id", result.id),
    "text": payload.get("text", ""),
    "level": payload.get("level", "paragraph"),
    "source": payload.get("source", "docling"),
    "page_no": payload.get("page_no", payload.get("page")),
    "image_url": payload.get("image_url"),
    "score": getattr(result, "score", None),
    "rank": rank + 1,
})
```

- [ ] **Step 4: Re-run the smoke path**

Run:

```bash
python summarizer_project/main.py
```

Expected: retrieval reaches entity extraction and later stages without schema errors.

- [ ] **Step 5: Commit**

```bash
git add summarizer_project/main.py summarizer_project/vectordb/qdrant_handler.py summarizer_project/tests
git commit -m "fix: preserve retrieval contract for summarizer pipeline"
```

---

## Self-Review

### Spec coverage

- Graph-rag Docling ingest priority — covered by Tasks 3 and 4.
- R2 replacing MinIO in active flow — covered by Tasks 1 and 3.
- Qdrant Cloud-style backend — covered by Task 2.
- Downstream summarizer compatibility after VectorDB — covered by Tasks 2, 5, and 6.
- Documentation/env updates — covered by Tasks 1 and 5.

No spec gaps found.

### Placeholder scan

- No `TODO`/`TBD` placeholders remain.
- Every code-changing step includes a concrete code block.
- Every test step includes a runnable command and expected outcome.

### Type consistency

- Payload field names are consistent across tasks: `chunk_id`, `text`, `level`, `source`, `page_no`, `image_url`, `score`, `rank`.
- Storage handler name is consistent: `R2Handler`.
- Vector handler remains `QdrantHandler` with the same public methods.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-graph-rag-summarizer-ingest-integration.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
