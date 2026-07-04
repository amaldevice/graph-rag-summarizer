# Graph RAG Summarizer

Graph RAG Summarizer is a prototype for long-document summarization.
It combines Docling preprocessing, selectable object storage, selectable Qdrant backends, graph analysis, and Groq-based summarization.

The repository separates ingestion from summarization:
- `upload_to_qdrant.py` indexes a document into Qdrant.
- `main.py` retrieves indexed chunks and generates a summary.

## Workflow

1. **Ingest**: PDF -> Docling -> chunks and images -> embeddings -> object storage -> Qdrant.
2. **Summarize**: query -> embedding -> Qdrant retrieval -> graph analysis -> pruning -> community summaries -> final summary -> evaluation.

## Repository Structure

- `config/` - environment-driven runtime settings.
- `preprocessing/` - Docling loading, image export, and on-demand page rendering.
- `storage/` - Cloudflare R2 and MinIO handlers.
- `vectordb/` - Qdrant connection and payload normalization.
- `embedding/`, `graph/`, `summarizer/`, `evaluation/`, `pipeline/` - core pipeline stages.
- `tests/` - targeted regression tests.
- `docker-compose.yml` - local Qdrant and MinIO stack.

## Backend Modes

| Mode | Object Storage | Vector Database | Required Selectors |
| --- | --- | --- | --- |
| Cloud | Cloudflare R2 | Qdrant Cloud | `STORAGE_BACKEND=r2`, `QDRANT_BACKEND=cloud` |
| Local | MinIO | Local Qdrant | `STORAGE_BACKEND=minio`, `QDRANT_BACKEND=local` |

`QDRANT_BACKEND=auto` resolves to `cloud` when `QDRANT_URL` is set, otherwise `local`.

Local mode uses `docker compose`.
The bundled `minio-init` job creates the `summarizer-images` bucket automatically.
Named volumes persist by default across local restarts.

## Setup

1. Create and activate a Python 3.10 environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install the spaCy model:
   ```bash
   python -m spacy download en_core_web_sm
   ```
4. Copy the environment template:
   ```bash
   cp env.example .env
   ```
5. Fill in the backend credentials and runtime settings.

## Minimum Configuration

Configure these values before running the pipeline:
- `STORAGE_BACKEND`
- `QDRANT_BACKEND`
- `QDRANT_COLLECTION`
- `GROQ_API_KEY`

For **cloud mode**, also configure:
- `QDRANT_URL`
- `QDRANT_API_KEY` if required
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

For **local mode**, also configure:
- `QDRANT_HOST`
- `QDRANT_PORT`
- `MINIO_ENDPOINT_URL`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PUBLIC_BASE_URL`

Optional runtime overrides include `PDF_PATH`, `QUERY_TEXT`, and `RETRIEVAL_LIMIT`.

## Quick Start

### Cloud Mode

```bash
cp env.example .env
# update .env for R2 + Qdrant Cloud
python upload_to_qdrant.py
python main.py
```

### Local Mode

```bash
docker compose up -d
cp env.example .env
# update .env for MinIO + local Qdrant
python upload_to_qdrant.py
python main.py
```

To stop the local stack:

```bash
docker compose down
```

## Outputs

The pipeline writes artifacts to `output/`.
This includes graph rankings, community summaries, the final summary, evaluation results, and the quality report.

## Tests

Run the targeted test suite with:

```bash
python scripts/run_targeted_pytest.py
```

## Current Scope

This repository is a working prototype.
Several conceptual pieces remain partial, including hierarchical chunking depth, graph edge coverage, evaluation breadth, and automated feedback-loop re-execution.
