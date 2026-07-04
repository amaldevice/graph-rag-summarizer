# Graph RAG Summarizer

Graph RAG Summarizer is a prototype pipeline for long-document retrieval and summarization. It combines Docling-based document extraction, selectable storage and Qdrant backends, graph analysis, and Groq-based summarization.

The repository separates ingestion from query-time summarization:

- `upload_to_qdrant.py` ingests a document into Qdrant.
- `main.py` retrieves indexed chunks and produces a summary.

## Architecture

1. **Ingest**: PDF → Docling → chunks and images → embeddings → object storage → Qdrant.
2. **Summarize**: query → embedding → Qdrant retrieval → graph analysis → pruning → community summaries → final summary → evaluation.

## Storage and Vector Backends

| Mode | Object Storage | Vector Database | Required Selectors |
| --- | --- | --- | --- |
| Cloud | Cloudflare R2 | Qdrant Cloud | `STORAGE_BACKEND=r2`, `QDRANT_BACKEND=cloud` |
| Local | MinIO | Local Qdrant | `STORAGE_BACKEND=minio`, `QDRANT_BACKEND=local` |

`QDRANT_BACKEND=auto` resolves to `cloud` when `QDRANT_URL` is set; otherwise it resolves to `local`.

Local mode uses `docker compose`, and the bundled named volumes preserve MinIO and Qdrant data across restarts by default.

## Setup

1. Install `uv`.
2. Sync the locked environment:

   ```bash
   uv sync --frozen
   ```

3. Install the spaCy model:

   ```bash
   uv run python -m spacy download en_core_web_sm
   ```

4. Copy the environment template and fill in the required settings:

   ```bash
   cp env.example .env
   ```

The repository is pinned to Python 3.12 through `.python-version`.

## Embedding Runtime

The repository now uses one shared embedding runtime contract for both ingest and query.

### Default behavior

| Host | Default backend | Default device |
| --- | --- | --- |
| macOS | `sentence-transformers` | `mps`, with automatic fallback to `cpu` |
| Windows | `sentence-transformers` | `cpu` |
| Linux | `sentence-transformers` | `cpu` |

Runtime startup logs report:

- requested backend and device,
- detected host platform,
- resolved backend and device,
- and any fallback reason.

### Key embedding settings

- `EMBEDDING_MODEL` — embedding model used by both ingest and query.
- `EMBEDDING_BACKEND` — `sentence-transformers` or `onnx`.
- `EMBEDDING_DEVICE` — `auto`, `cpu`, or `mps`.
- `EMBEDDING_LOCAL_FILES_ONLY` — disable remote downloads when set to `True`.
- `EMBEDDING_TRUST_REMOTE_CODE` — enables remote model code only when the current model is also present in the trust allowlist.
- `EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS` — comma-separated allowlist for models that may run remote upstream code.
- `EMBEDDING_ONNX_ALLOWED_MODELS` — comma-separated ONNX allowlist.

### Local caches

All embedding downloads and local export artifacts stay under the repository root:

- `.cache/embedding/models/`
- `.cache/embedding/onnx/`

These paths are ignored by Git and are never intended for the remote repository.

### Optional ONNX mode

ONNX remains optional and experimental in this repository.

Install the optional group only when needed:

```bash
uv sync --frozen --group onnx
```

Current project behavior:

- ONNX is CPU-only in this repository.
- ONNX is allowlist-gated.
- If ONNX is requested but dependencies are missing, the model is not allowlisted, or ONNX initialization fails, the runtime warns and falls back to the standard `sentence-transformers` path with the same `EMBEDDING_MODEL`.
- The default Nomic model remains the standard backend path.
- ONNX is not a drop-in accelerator for the default Nomic model in this repository; it is a separate opt-in path for supported models such as `sentence-transformers/all-MiniLM-L6-v2`.

Example ONNX configuration:

```bash
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
EMBEDDING_BACKEND=onnx \
EMBEDDING_DEVICE=auto \
EMBEDDING_TRUST_REMOTE_CODE=False \
EMBEDDING_ONNX_ALLOWED_MODELS=sentence-transformers/all-MiniLM-L6-v2
```

## Minimum Configuration

Set these before running the pipeline:

- `STORAGE_BACKEND`
- `QDRANT_BACKEND`
- `QDRANT_COLLECTION`
- `GROQ_API_KEY`

For cloud mode, also set:

- `QDRANT_URL`
- `QDRANT_API_KEY` if required
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

For local mode, also set:

- `QDRANT_HOST`
- `QDRANT_PORT`
- `MINIO_ENDPOINT_URL`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PUBLIC_BASE_URL`

Useful runtime overrides include `PDF_PATH`, `QUERY_TEXT`, and `RETRIEVAL_LIMIT`.

## Quick Start

### Local mode

```bash
docker compose up -d
cp env.example .env
# update .env for MinIO + local Qdrant
uv run python upload_to_qdrant.py
uv run python main.py
```

Stop the local stack with:

```bash
docker compose down
```

### Cloud mode

```bash
cp env.example .env
# update .env for R2 + Qdrant Cloud
uv run python upload_to_qdrant.py
uv run python main.py
```

## Outputs

Pipeline artifacts are written to `output/`, including graph rankings, community summaries, final summaries, evaluation results, and quality reports.

## Tests

Run the targeted regression suite with:

```bash
uv run python scripts/run_targeted_pytest.py
```
