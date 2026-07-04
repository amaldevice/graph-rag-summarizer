# Dual Local/Cloud Storage and Qdrant Design

Date: 2026-07-04
Status: Approved for planning
Scope: Extend the current graph-rag-based ingest inside `summarizer_project` so the same codebase can run in **local Docker mode** (`MinIO + Qdrant local`) or **cloud mode** (`R2 + Qdrant Cloud`) without changing the downstream summarization pipeline.

## Goal

Make the ingest boundary in `summarizer_project` support two infrastructure profiles:

- **Cloud mode** for the current Colab-friendly path:
  - object storage via Cloudflare R2
  - vector storage via Qdrant Cloud
- **Local mode** for developer/self-hosted runs:
  - object storage via MinIO from `docker-compose.yml`
  - vector storage via local Qdrant from `docker-compose.yml`

Keep the following architectural rule unchanged:

- `graph_rag-pipeline` direction remains the source of truth from **Input Document -> Preprocessing -> Chunking -> Embedding -> Vector DB Storage**
- `summarizer_project` remains the source of truth for everything **after retrieval from Vector DB**

## Non-Goals

- Replacing the existing graph/entity/summarization/evaluation pipeline.
- Replacing Docling ingest with another parser.
- Introducing a third object-storage provider beyond R2 and MinIO.
- Replacing Qdrant with another vector database.
- Rewriting the downstream payload contract used by `main.py`, `graph/*`, or `summarizer/*`.

## Current State Snapshot

Observed from the current codebase:

### Active ingest/storage state

- `summarizer_project/preprocessing/docling_loader.py` currently hardwires `R2Handler`.
- `summarizer_project/storage/r2_handler.py` is the only active object-storage backend.
- `summarizer_project/config/settings.py` only exposes active R2 settings, not MinIO settings.
- `summarizer_project/env.example` documents the cloud-first path, not a dual-mode path.

### Active vector DB state

- `summarizer_project/vectordb/qdrant_handler.py` already supports:
  - `QDRANT_URL` + `QDRANT_API_KEY`
  - or fallback `QDRANT_HOST` + `QDRANT_PORT`
- Selection is currently **implicit**, not explicitly documented as a supported dual-mode contract.

### Local infra state

- `summarizer_project/docker-compose.yml` still defines:
  - `qdrant`
  - `minio`
- but the live ingest code no longer consumes MinIO, so the local stack is partially orphaned.

### Constraint from repository instructions

- Python execution for this repository is expected to happen via **Google Colab CLI**, not local Python.
- That means:
  - **Cloud mode** is the easiest mode to verify end-to-end with current repo rules.
  - **Local Docker mode** is still valid and useful, but its verification should rely on Docker plumbing and/or containerized smoke checks, not ad-hoc host Python runs.

## Decision Summary

Adopt a **thin adapter dual-mode design**:

1. Keep the graph-rag ingest direction already merged into `summarizer_project`.
2. Introduce a **backend-neutral object storage interface** inside `summarizer_project/storage/`.
3. Support `STORAGE_BACKEND=r2|minio`.
4. Support `QDRANT_BACKEND=auto|cloud|local`.
5. Preserve the existing retrieved chunk contract used by downstream summarizer code.
6. Restore `docker-compose.yml` as the official **local mode** bootstrap path.

This keeps the codebase small, avoids forking the ingest flow, and makes local/cloud switching an environment concern rather than a code-edit concern.

## Target Architecture

### High-level flow

```text
Input PDF
  -> summarizer_project/upload_to_qdrant.py
  -> summarizer_project/preprocessing/docling_loader.py
  -> summarizer_project/preprocessing/image_exporter.py
  -> summarizer_project/storage/factory.py
       -> R2Handler      (cloud mode)
       -> MinIOHandler   (local mode)
  -> summarizer_project/embedding/embedder.py
  -> summarizer_project/vectordb/qdrant_handler.py
       -> Qdrant Cloud   (cloud mode)
       -> Qdrant Local   (local mode)
  -> retrieval
  -> summarizer_project/main.py
  -> graph/entity extraction onward
```

### Mode matrix

| Concern | Cloud mode | Local mode |
| --- | --- | --- |
| Object storage | R2 | MinIO |
| Vector DB | Qdrant Cloud | Docker Qdrant |
| Backend selector | `STORAGE_BACKEND=r2` | `STORAGE_BACKEND=minio` |
| Qdrant selector | `QDRANT_BACKEND=cloud` | `QDRANT_BACKEND=local` |
| Best-fit execution path | Colab CLI | Docker/local infra |

## Flow Mapping to the Diagram

This maps the earlier target flow diagram to current `summarizer_project` code ownership.

### 1. Input Document

- Entry: `summarizer_project/upload_to_qdrant.py`

### 2. Preprocessing

- `summarizer_project/preprocessing/docling_loader.py`
- `summarizer_project/preprocessing/image_exporter.py`

Responsibilities:

- load PDF via Docling
- extract structural text
- export page/embedded images
- attach page metadata

### 3. Adaptive Hierarchical Chunking

- current boundary: `DoclingLoader.chunk_text()`

Note:

- current implementation is still Docling-item-based, not a new custom chunk hierarchy engine.
- this design does **not** replace that behavior; it only makes the storage/vector backend selectable.

### 4. Embedding

- `summarizer_project/embedding/embedder.py`

### 5. Vector DB Storage

- `summarizer_project/vectordb/qdrant_handler.py`

Responsibilities to preserve:

- create collection if needed
- upsert vectors with payload
- normalize retrieval payload for downstream summarizer stages

### 6. Hybrid Entity Extraction onward

These stages remain unchanged and stay owned by `summarizer_project`:

- `graph/entity_extractor.py`
- `graph/graph_builder.py`
- `graph/community_detector.py`
- `graph/graph_analyzer.py`
- `summarizer/pruner.py`
- `summarizer/prompt_builder.py`
- `summarizer/llm_summarizer.py`
- `summarizer/hierarchical_reducer.py`
- `evaluation/evaluator.py`
- `evaluation/quality_checker.py`
- `pipeline/feedback_loop.py`

## Required Data Contract

The ingest and retrieval layers must continue returning chunk dictionaries with:

- `chunk_id`
- `text`
- `level`
- `source`
- `page_no`
- `image_url`

Retrieval-time augmentation must continue including:

- `score`
- `rank`

### Contract rules

1. `page_no` remains the canonical downstream page field.
2. `page` may still be stored for compatibility, but adapter code normalizes back to `page_no`.
3. `image_url` must come from the active storage backend:
   - R2 URL in cloud mode
   - MinIO/public local URL in local mode
4. Backend switching must not force changes in downstream graph/summarizer code.

## Configuration Model

### New/explicit selectors

```env
STORAGE_BACKEND=r2
QDRANT_BACKEND=auto
```

Accepted values:

- `STORAGE_BACKEND`: `r2`, `minio`
- `QDRANT_BACKEND`: `auto`, `cloud`, `local`

### Cloud profile

```env
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=replace_me
R2_ACCESS_KEY_ID=replace_me
R2_SECRET_ACCESS_KEY=replace_me
R2_BUCKET=replace_me
R2_PUBLIC_BASE_URL=https://pub-example.r2.dev

QDRANT_BACKEND=cloud
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=replace_me
QDRANT_COLLECTION=summarizer_docs
```

### Local Docker profile

```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT_URL=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=summarizer-images
MINIO_PUBLIC_BASE_URL=http://localhost:9000/summarizer-images

QDRANT_BACKEND=local
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=summarizer_docs_local
```

### Backward-compatibility rule

- `QDRANT_BACKEND=auto` preserves the current behavior:
  - if `QDRANT_URL` is set, use cloud
  - otherwise use local host/port

## Design Changes by Area

### 1. `summarizer_project/config/settings.py`

Add explicit backend selectors and restore MinIO config values alongside the existing R2 and Qdrant values.

### 2. `summarizer_project/storage/`

Introduce a small backend-neutral layer:

- `base.py` or equivalent protocol for the shared storage contract
- `factory.py` to choose the active backend
- `minio_handler.py` to restore local object-storage support
- keep `r2_handler.py` for cloud mode

The shared contract should stay minimal:

- `upload_local_path(...)`
- `build_image_url(...)`

### 3. `summarizer_project/preprocessing/docling_loader.py`

Replace the current hardwired `R2Handler` dependency with the storage factory result.

Important:

- chunk metadata shape must remain unchanged
- only the storage backend selection becomes dynamic

### 4. `summarizer_project/vectordb/qdrant_handler.py`

Keep the current payload normalization, but make backend selection explicit and documented.

Expected behavior:

- `cloud` -> `QdrantClient(url=..., api_key=...)`
- `local` -> `QdrantClient(host=..., port=...)`
- `auto` -> preserve current fallback behavior

### 5. `summarizer_project/docker-compose.yml`

Turn the file back into a first-class local infra definition by:

- keeping Qdrant local
- keeping MinIO local
- adding a bucket-init path if needed so the MinIO bucket exists without manual setup

### 6. `summarizer_project/test_database/` and tests

Make integration naming backend-neutral:

- current `qdrant_r2_test.py` should become backend-neutral in naming and output
- unit tests should cover:
  - storage backend selection
  - MinIO handler URL/upload behavior
  - Docling loader integration with the storage factory
  - Qdrant backend selection and retrieved chunk contract

### 7. `summarizer_project/README.md`

Document two supported runtime profiles:

- Cloud/Colab profile
- Local Docker profile

Also clarify that **post-VectorDB flow is unchanged**.

## Migration Strategy

### Phase 1 — make backend selection explicit

- add config selectors
- add storage abstraction
- restore MinIO backend

### Phase 2 — wire ingest to the abstraction

- update `DoclingLoader`
- keep chunk and image metadata contract unchanged

### Phase 3 — formalize vector DB dual mode

- add explicit Qdrant backend selection
- preserve retrieval payload contract

### Phase 4 — restore local stack usability

- align docker-compose and env docs with the live code path
- make integration smoke output backend-neutral

## Risks

### 1. Backend drift in `DoclingLoader`

Risk:

- the code compiles but still names variables/paths as R2-specific, which can confuse future changes

Mitigation:

- rename the live field from `r2_handler` to `storage_handler`

### 2. Public URL mismatch in local mode

Risk:

- MinIO uploads work but generated URLs are unusable from the operator environment

Mitigation:

- keep `MINIO_PUBLIC_BASE_URL` explicit instead of deriving it implicitly

### 3. Bucket existence gap

Risk:

- local mode fails on first upload because the MinIO bucket was never created

Mitigation:

- create/init bucket from Docker bootstrap or document it as part of local stack startup

### 4. Hidden downstream schema regressions

Risk:

- backend refactor accidentally drops `page_no`, `level`, or `image_url`

Mitigation:

- keep unit tests focused on the downstream chunk contract

### 5. Verification asymmetry

Risk:

- cloud mode is easy to verify through Colab; local mode is harder under the repo’s “no local Python” rule

Mitigation:

- treat Docker config validation and backend-neutral smoke documentation as required implementation outputs

## Testing Strategy

### Required verification

1. Unit tests for storage factory and MinIO handler
2. Unit tests for Docling loader storage integration
3. Unit tests for Qdrant local/cloud/auto selection
4. Docker config validation for the local stack
5. Backend-neutral integration smoke script output for cloud mode

### Verification rule

- cloud-mode Python validation should continue using Colab CLI
- local-mode infra validation should rely on Docker/bootstrap verification rather than ad-hoc host Python

## Result

After this design is implemented:

- `summarizer_project` keeps the graph-rag ingest merge already in place
- cloud mode continues to work for Colab-driven usage
- local Docker mode becomes useful again
- the downstream flow after Vector DB Storage remains unchanged
