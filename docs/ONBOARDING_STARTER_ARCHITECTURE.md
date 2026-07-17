# Graph RAG Summarizer — Starter Architecture

Compact orientation for a new agent. Read this before changing implementation code.

> **Current boundary:** Each collection is explicitly `document-safe` (default)
> or `legacy-vector`. Document-safe ingest can publish a fenced,
> document-scoped persistent graph artifact; a Full-Pipeline Run reuses it when
> valid. Legacy-vector runs use the raw vector plane and build a compatibility
> graph at query time. Query-Only remains retrieval-only.

## 1. Purpose and mental model

This project turns long PDFs into query-grounded summaries:

```text
PDF ──Docling──> hierarchical chunks ──embed──> Qdrant + optional graph artifact
                                                │
query ──embed──────────────────────────────────┘
  └─ retrieve → reuse persistent graph (or compatibility graph) → communities
     → rank / score bounded evidence paths / allocate prompt context
     → map summaries → similarity-grouped reduction
     → evaluate selected evidence → quality gate → bounded feedback retry
```

Qdrant is the vector/payload store. R2 or MinIO stores extracted/rendered
images and, when enabled, the persistent graph artifact/manifest. Per-run
artifacts remain under `output/`.

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
| `ingest` | PDF → Docling → chunks/images → embeddings → Qdrant → optional graph artifact | summary, evaluation |
| `query-only` | query → embedding → Qdrant ranked chunks → console/JSON | graph, summary, evaluation |
| `full-pipeline` | retrieval → graph → summarize → evaluate → artifacts | — |

The launcher asks for the collection design immediately after the launcher
mode. The selected design is part of the collection contract, not a per-query
fallback: the first ingest pins it in the collection manifest and conflicting
later ingests fail before Qdrant mutation.

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
4. Ingest pins the selected collection design before Qdrant mutation.
5. `QdrantHandler.prepare_ingest()` applies the collection lifecycle.
6. `QdrantHandler.upsert_chunks()` writes vector + payload points in bounded batches.
7. In document-safe mode, `PersistentGraphPipeline` claims,
   validates, and publishes the document artifact and manifest entry.

Ingest operations are explicit: `append`, `replace-document`, and `replace-collection`. Legacy points without `document_id` must be rebuilt before document-safe append/replacement.
`legacy-vector` ingest remains vector-only: it does not reserve a document
claim, publish a graph/control point, or call the relation provider.

### Full-Pipeline Run

`launcher/runners.py::run_full_pipeline` executes the stages in this order:

1. **Retrieve** — embed the query and call `QdrantHandler.search_as_chunks()`.
   Document-safe retrieval uses manifest generations and tombstone denial;
   legacy-vector retrieval deliberately uses the raw vector plane. Empty
   retrieval stops here with a recovery-oriented error.
2. **Load or build graph** — reuse a validated persistent artifact when enabled;
   otherwise extract entities/relations and build the compatibility query graph.
   If that graph fails, use observable vector-only context.
3. **Use communities** — reuse persisted communities or detect them in the
   compatibility graph.
4. **Analyze/prune** — `GraphAnalyzer` ranks nodes; `SummaryPruner` enumerates
   bounded retrieved-chunk paths, scores retrieval/centrality/length/diversity,
   and allocates selected evidence within the character budget. Selected path
   IDs and rejected-path reasons remain in the pruned-context artifact.
5. **Map** — `PromptBuilder` creates NAP/CAP/CGM prompts; `LLMSummarizer`
   summarizes communities.
6. **Reduce** — `HierarchicalReducer` merges community summaries into the final
   answer. Larger runs group embedding-similar summaries per level and record
   the groups; invalid vectors use a deterministic stable-ID fallback.
7. **Evaluate/retry** — evaluator evaluates the selected evidence with
   lightweight grounded metrics; `QualityChecker` and `FeedbackLoopController`
   may retry retrieval, prompting, or reduction within a bound.

## 5. Source map

| Path | Responsibility |
| --- | --- |
| `launcher/contract.py` | CLI contract, mode/profile resolution, input validation, stable IDs |
| `launcher/runners.py` | Orchestration for all three modes |
| `preprocessing/` | Docling parsing, hierarchy-aware chunk payloads, image export |
| `embedding/` | Text embedding, device/backend resolution, local caches |
| `vectordb/qdrant_handler.py` | Qdrant lifecycle, payload normalization, upsert, search |
| `storage/` | R2/MinIO selection and object upload/URL generation |
| `graph/` | Entity/relation extraction, persistent graph lifecycle, construction, communities, ranking artifacts |
| `summarizer/` | Bounded path-aware evidence pruning, prompts, provider routing, map/reduce |
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
persistent_graph_read.json (when a persistent read is unavailable)
pruned_summary_context.csv/json
context_allocation.json
community_map_summaries.txt/json
final_summary.txt/json
evaluation_result.json
quality_gate_report.json
feedback_loop_decision.json
```

`pruned_summary_context.json` contains the explicit path selection; final
summary JSON contains reduction-level groups. Retry attempts are placed under
`artifact_dir/attempt-*`; their quality and feedback artifacts include the
attempt number.

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
- **Collection design is exclusive:** document-safe collections use manifest
  authorization and persistent artifacts; legacy-vector collections use raw
  vector retrieval and compatibility graphs. A caller must select the
  collection's matching design; no automatic cross-design fallback exists.
- **Qdrant is not a graph database:** it stores vectors and payload metadata; graph topology is assembled in Python.
- **Images are optional enrichment:** PDF access and embedding inference remain local to the machine running the launcher, even in `cloud` profile.
- **LLM is required only for Full-Pipeline:** Query-Only and Ingest can operate without a configured provider.
- **Forced retry is test-only:** the private direct-run seam is intentionally
  absent from the launcher CLI; normal Full-Pipeline runs use only real quality
  decisions.
