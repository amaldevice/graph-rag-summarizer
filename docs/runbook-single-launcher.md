# Single Launcher Runbook

This project is operated through `main.py`.
The launcher asks for session-specific inputs at runtime, while `.env` stores stable defaults and credentials.

## What the launcher can do

- **`ingest`** — read one local PDF, chunk it, embed it, then append or replace document data in a Qdrant collection.
- **`query-only`** — embed one query, retrieve ranked chunks from Qdrant, then optionally save a JSON artifact.
- **`full-pipeline`** — retrieve chunks, reuse/build the graph, select bounded
  path-aware evidence, summarize, evaluate, retry when the quality gate asks,
  and write downstream artifacts into one artifact directory.

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
4. Resolve collection design: `document-safe` (default) or `legacy-vector`
5. If interactive, ask for any missing inputs
6. Show a run summary and ask for confirmation
7. Execute one mode runner:
   - `ingest` → PDF -> Docling -> chunks -> document-safe IDs -> embeddings -> Qdrant lifecycle -> Qdrant
   - `query-only` → query -> embedding -> Qdrant retrieval -> console output / JSON
   - `full-pipeline` → retrieval -> persistent/compatibility/vector graph
     fallback -> path-aware evidence allocation -> map summaries ->
     embedding-similar reduction -> evaluation/retry -> reports

## Interactive flow

If you run `uv run python main.py` in a TTY, the launcher can prompt for:

- profile
- mode
- collection design (immediately after mode)
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

`--collection-mode document-safe` is the default. Use
`--collection-mode legacy-vector` only for a collection intentionally kept on
the raw-vector design; its first ingest pins that choice in the collection
manifest. A collection cannot later switch designs implicitly.

`append` safely rejects an existing `--document-id`. Use `replace-document` to replace one document or `replace-collection` to intentionally rebuild the collection.

## CLI arguments

| Argument | Meaning | Used by |
| --- | --- | --- |
| `--mode` | Launcher mode: `query-only`, `ingest`, `full-pipeline` | all |
| `--profile` | Launch profile: `local` or `cloud` | all |
| `--collection` | Qdrant collection target | query-only, ingest, full-pipeline |
| `--collection-mode` | Collection design: `document-safe` (default) or `legacy-vector` | all |
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
  --collection-mode document-safe \
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
  --collection-mode document-safe \
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
  --collection-mode document-safe \
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
- collection design
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
- Full-Pipeline writes explicit selected path IDs and rejected-path reasons to
  `pruned_summary_context.json`, allocation decisions to
  `context_allocation.json`, and reduction groups to `final_summary.json`.
- Quality retries are bounded and store follow-up artifacts in
  `artifact_dir/attempt-*`; ordinary launcher input cannot force a retry. The
  forced-failure seam is private to direct test/dev callers.
- Non-verbose runs still print the current stage; `--verbose` adds higher-detail stage context.
- The launcher checks configuration presence, not end-to-end remote health. Use `uv run python scripts/check_cloud_connections.py` to validate Qdrant Cloud and R2 connectivity separately.
- `document-safe` collections keep the manifest, generation, tombstone, and
  persistent-graph safeguards. `legacy-vector` collections use the original
  raw vector plane for Query-Only and Full-Pipeline compatibility graphs and
  deliberately skip document-safe lifecycle/LLM graph publishing on ingest.
- Full-Pipeline now stops with an actionable error when retrieval returns no
  chunks; it does not attempt graph analysis on an empty result.
