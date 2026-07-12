# Graph RAG Summarizer — Starter Architecture

Compact orientation for a new agent. Read this before changing implementation code.

> **Current boundary:** the project is graph-aware, but graph construction currently happens during a **Full-Pipeline Run** after Qdrant retrieval. Ingest persists vectors and payload metadata; it does not yet persist a reusable graph.

## 1. Purpose and mental model

This project turns long PDFs into query-grounded summaries:

```text
PDF ──Docling──> hierarchical chunks ──embed──> Qdrant
                                                │
query ──embed──────────────────────────────────┘
  └─ retrieve → extract entities/relations → build graph → communities
     → rank/prune evidence → map summaries → reduce final summary
     → evaluate → quality gate → bounded feedback retry
```

Qdrant is the vector/payload store. R2 or MinIO stores extracted/rendered images. The graph is built in memory with per-run artifacts written under `output/`.

## 2. Technology stack

| Area | Implementation |
| --- | --- |
| Runtime | Python 3.12, `uv` |
| PDF parsing | Docling |
| Embeddings | Sentence Transformers; optional ONNX runtime |
| Vector store | Qdrant local or Qdrant Cloud |
| Object storage | Cloudflare R2 or MinIO |
| Graph | NetworkX; igraph + Leiden community detection |
| Entities/relations | spaCy entities, LLM extraction when available, rule fallback |
| Summarization | Provider-routed LLM map/reduce with Groq/Gemini/NVIDIA/OpenRouter fallbacks |
| Evaluation | ROUGE/BERTScore/reference metrics plus lightweight quality checks |
| Tests | pytest |

## 3. Entry point and launcher modes

`main.py` is the only human-facing launcher. Configuration precedence is:

```text
CLI flags → interactive wizard → .env/config stable defaults
```

Per-run choices are session overrides; the launcher does not rewrite `.env`.

| Mode | Flow | Does not do |
| --- | --- | --- |
| `ingest` | PDF → Docling → chunks/images → embeddings → Qdrant | graph, summary, evaluation |
| `query-only` | query → embedding → Qdrant ranked chunks → console/JSON | graph, summary, evaluation |
| `full-pipeline` | retrieval → graph → summarize → evaluate → artifacts | — |

Profiles select infrastructure, not work:

| Profile | Vectors | Images |
| --- | --- | --- |
| `local` | Local Qdrant | MinIO |
| `cloud` | Qdrant Cloud | Cloudflare R2 |

## 4. Runtime flows

### Ingest Run

`launcher/runners.py::run_ingest`:

1. `DoclingLoader.process_pdf()` extracts text, hierarchy/layout metadata, and optional images.
2. `_stamp_document_identity()` adds `document_id`, deterministic `chunk_uid`, and parent references.
3. `TextEmbedder.embed_chunks()` creates vectors.
4. `QdrantHandler.prepare_ingest()` applies the collection lifecycle.
5. `QdrantHandler.upsert_chunks()` writes vector + payload points in bounded batches.

Ingest operations are explicit: `append`, `replace-document`, and `replace-collection`. Legacy points without `document_id` must be rebuilt before document-safe append/replacement.

### Full-Pipeline Run

`launcher/runners.py::run_full_pipeline` executes the stages in this order:

1. **Retrieve** — embed the query and call `QdrantHandler.search_as_chunks()`.
2. **Extract** — obtain entities and relations from retrieved chunks.
3. **Build graph** — `GraphBuilder` creates chunk/entity nodes and mention, relation, and similarity edges.
4. **Detect communities** — `CommunityDetector` applies Leiden modularity partitioning.
5. **Analyze/prune** — `GraphAnalyzer` ranks nodes; `SummaryPruner` selects evidence per community and globally.
6. **Map** — `PromptBuilder` creates NAP/CAP/CGM prompts; `LLMSummarizer` summarizes communities.
7. **Reduce** — `HierarchicalReducer` merges community summaries into the final answer.
8. **Evaluate/retry** — evaluator + quality checker produce a decision; `FeedbackLoopController` may retry retrieval, prompting, or reduction within a bound.

## 5. Source map

| Path | Responsibility |
| --- | --- |
| `launcher/contract.py` | CLI contract, mode/profile resolution, input validation, stable IDs |
| `launcher/runners.py` | Orchestration for all three modes |
| `preprocessing/` | Docling parsing, hierarchy-aware chunk payloads, image export |
| `embedding/` | Text embedding, device/backend resolution, local caches |
| `vectordb/qdrant_handler.py` | Qdrant lifecycle, payload normalization, upsert, search |
| `storage/` | R2/MinIO selection and object upload/URL generation |
| `graph/` | Entity/relation extraction, graph construction, communities, ranking artifacts |
| `summarizer/` | Evidence pruning, prompts, provider routing, map/reduce |
| `evaluation/` | Summary metrics, quality status, retry recommendation |
| `pipeline/feedback_loop.py` | Bounded stage retry decisions and artifacts |
| `tests/test_flowchart_alignment.py` | Cross-module architecture seam/regression tests |
| `docs/runbook-single-launcher.md` | Operator-facing launcher contract |
| `CONTEXT.md` | Canonical domain vocabulary |

## 6. Core data contracts

### Chunk payload

The canonical chunk travels from Docling to embeddings, Qdrant, graph, and summarization. Important fields:

```text
text, chunk_id, document_id, chunk_uid, page_no,
hierarchy: section/paragraph IDs, parent_chunk_id, path,
layout, image_url, source
```

`chunk_uid` identifies a logical chunk across runs. Qdrant point IDs are deterministic from `document_id + chunk_id`; do not use a local `chunk_id` alone in a shared collection.

### Full-Pipeline artifacts

The selected `artifact_dir` receives:

```text
graph_ranked_nodes.csv/json
graph_summary.json
pruned_summary_context.csv/json
community_map_summaries.txt/json
final_summary.txt/json
evaluation_result.json
quality_gate_report.json
feedback_loop_decision.json
```

Retry attempts are placed under `artifact_dir/attempt-*`.

## 7. Configuration and commands

Stable defaults and credentials live in `.env`; see `config/settings.py` and `.env.example`. The most important selectors are `LAUNCHER_PROFILE`, `QDRANT_BACKEND`, `QDRANT_COLLECTION`, `STORAGE_BACKEND`, embedding settings, and LLM provider/fallback settings.

```bash
uv sync --frozen
uv run python main.py --help
uv run python main.py --no-interactive --mode query-only \
  --collection <collection> --query "<question>"
uv run pytest -q
```

Do not run live ingest/full-pipeline against a real collection without explicit collection, document, provider, and credential context.

## 8. Recommended onboarding order

1. Read `CONTEXT.md`, then `docs/adr/0001-profile-driven-single-launcher.md`.
2. Read `main.py`, `launcher/contract.py`, and `launcher/runners.py`.
3. Trace ingest through `preprocessing/`, `embedding/`, `vectordb/`, and `storage/`.
4. Trace Full-Pipeline stages through `graph/`, `summarizer/`, `evaluation/`, and `pipeline/`.
5. Use `tests/test_flowchart_alignment.py` plus the nearest module test as executable contracts.
6. Read `docs/runbook-single-launcher.md` before changing CLI/config behavior.

## 9. Important boundaries

- **Not Microsoft GraphRAG:** there is no GraphRAG package contract, persistent GraphRAG parquet index, or Neo4j requirement in the current flow.
- **Not ingest-time graph persistence:** reusable graph construction during ingest is a planned follow-up; current graph artifacts are derived per Full-Pipeline Run.
- **Qdrant is not a graph database:** it stores vectors and payload metadata; graph topology is assembled in Python.
- **Images are optional enrichment:** PDF access and embedding inference remain local to the machine running the launcher, even in `cloud` profile.
- **LLM is required only for Full-Pipeline:** Query-Only and Ingest can operate without a configured provider.
