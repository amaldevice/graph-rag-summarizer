# Single Launcher Runbook

This project is operated through `main.py`.
The launcher asks for session-specific inputs at runtime, while `.env` stores stable defaults and credentials.

## What the launcher can do

- **`ingest`** — read one local PDF, chunk it, embed it, then append or replace document data in a Qdrant collection.
- **`query-only`** — embed one query, retrieve ranked chunks from Qdrant, then optionally save a JSON artifact.
- **`full-pipeline`** — retrieve chunks, build the graph, summarize, evaluate, and write the downstream artifacts into one artifact directory.

## Profile behavior

A **Launch Profile** chooses the infrastructure pair for the current run:

- **`local`** → local Qdrant + MinIO
- **`cloud`** → Qdrant Cloud + Cloudflare R2

Profile precedence is:

1. `--profile`
2. `LAUNCHER_PROFILE` in `.env`
3. backend auto-detection fallback

At runtime, the launcher also applies these session overrides:

- `local` → `QDRANT_BACKEND=local`, `STORAGE_BACKEND=minio`
- `cloud` → `QDRANT_BACKEND=cloud`, `STORAGE_BACKEND=r2`

## Real execution flow

1. Load `.env`
2. Resolve profile
3. Resolve mode
4. If interactive, ask for any missing inputs
5. Show a run summary and ask for confirmation
6. Execute one mode runner:
   - `ingest` → PDF -> Docling -> chunks -> document-safe IDs -> embeddings -> Qdrant lifecycle -> Qdrant
   - `query-only` → query -> embedding -> Qdrant retrieval -> console output / JSON
   - `full-pipeline` → retrieval -> graph -> summarization -> evaluation -> reports

## Interactive flow

If you run `uv run python main.py` in a TTY, the launcher can prompt for:

- profile
- mode
- collection name
- query text
- retrieval limit
- PDF path
- JSON output path for `query-only`
- artifact output directory for `full-pipeline`
- verbose logging toggle
- ingest mode and optional document ID through CLI arguments

For ingest, the launcher can scan the repo for local PDF files and suggest a collection name and document ID from the PDF filename.

## Non-interactive flow

Use `--no-interactive` when you want a fail-fast CLI run.
Required inputs are enforced by mode:

- **`query-only`** → `--collection`, `--query`
- **`ingest`** → `--pdf` (`--collection` optional; if omitted, it is derived from the PDF filename; mode defaults to `append`)
- **`full-pipeline`** → `--collection`, `--query`

`append` safely rejects an existing `--document-id`. Use `replace-document` to replace one document or `replace-collection` to intentionally rebuild the collection.

## CLI arguments

| Argument | Meaning | Used by |
| --- | --- | --- |
| `--mode` | Launcher mode: `query-only`, `ingest`, `full-pipeline` | all |
| `--profile` | Launch profile: `local` or `cloud` | all |
| `--collection` | Qdrant collection target | query-only, ingest, full-pipeline |
| `--query` | Query text | query-only, full-pipeline |
| `--retrieval-limit` | Number of retrieved chunks; default `10` | query-only, full-pipeline |
| `--pdf` | Local PDF path for ingest, or optional page-image enrichment in full-pipeline | ingest, full-pipeline |
| `--json-output` | Output JSON artifact path | query-only |
| `--artifact-dir` | Output directory for Full-Pipeline artifacts | full-pipeline |
| `--verbose` | Enable clearer stage-level diagnostic logging | all |
| `--no-interactive` | Disable prompts and require explicit CLI inputs | all |
| `--ingest-mode` | Collection operation: `append`, `replace-document`, or `replace-collection`; default `append` | ingest |
| `--document-id` | Stable document ID; defaults to the PDF filename | ingest |

## Minimal commands

### Interactive

```bash
uv run python main.py
```

### Query-only

```bash
uv run python main.py \
  --no-interactive \
  --mode query-only \
  --profile cloud \
  --collection let_them_book \
  --query "What is the main thesis?"
```

### Ingest

```bash
uv run python main.py \
  --no-interactive \
  --mode ingest \
  --profile cloud \
  --pdf sample.pdf \
  --collection sample_pdf \
  --document-id sample-pdf \
  --ingest-mode append
```

### Full pipeline

```bash
uv run python main.py \
  --no-interactive \
  --mode full-pipeline \
  --profile cloud \
  --collection sample_pdf \
  --query "Summarize the core ideas" \
  --artifact-dir output/full_pipeline_sample \
  --verbose
```

## What should stay in `.env`

Keep stable configuration and credentials in `.env`, for example:

- Qdrant connection values
- R2 or MinIO credentials
- embedding defaults
- LLM provider API keys and model defaults

Good candidates for runtime input are:

- mode
- profile
- collection
- query
- PDF path
- retrieval limit
- JSON output path for `query-only`
- artifact output directory for `full-pipeline`

## Current runtime notes

- Even in **cloud** profile, the PDF is still read from the local filesystem or the host machine that runs `main.py`.
- Embedding inference still runs on the same machine that launches the app.
- `full-pipeline` requires at least one configured LLM provider.
- Persistent graph artifacts are enabled by default through
  `ENABLE_PERSISTENT_GRAPH`. Ingest publishes a document-scoped graph artifact
  when that stage is enabled; Full-Pipeline reuses a validated artifact when
  available and records a compatibility/vector fallback otherwise.
- Non-verbose runs still print the current stage; `--verbose` adds higher-detail stage context.
- The launcher checks configuration presence, not end-to-end remote health. Use `uv run python scripts/check_cloud_connections.py` to validate Qdrant Cloud and R2 connectivity separately.
- Shared collections support document-safe `append`, `replace-document`, and `replace-collection` ingest modes. Legacy collections without `document_id` must be rebuilt with `replace-collection` first.
