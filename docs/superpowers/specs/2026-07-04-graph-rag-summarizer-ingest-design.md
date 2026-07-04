# Graph-RAG Ingest Integration Design

Date: 2026-07-04
Status: Approved for planning
Scope: Replace `summarizer_project` ingest/storage infrastructure with the Docling-based `graph_rag-pipeline` flow, while keeping the post-VectorDB pipeline in `summarizer_project`.

## Goal

Make `graph_rag-pipeline` the source of truth for:

- document ingest,
- image/object storage,
- embedding choice,
- Qdrant connection style,
- and any conflicting ingest-side flow.

Keep `summarizer_project` as the source of truth for everything after retrieval from VectorDB:

- entity extraction,
- graph construction,
- community detection,
- graph analysis,
- pruning and reranking,
- prompt construction,
- map/reduce summarization,
- evaluation,
- quality gate,
- feedback loop.

## Non-Goals

- Replacing the graph pipeline in `summarizer_project`.
- Replacing summarization or evaluation with anything from `graph_rag-pipeline`.
- Preserving MinIO as an active storage backend.
- Doing a full payload-schema rewrite across all downstream modules.

## Decision Summary

Use the **Option B / thin adapter merge**:

1. Ingest follows the **graph-rag Docling flow**.
2. Image/object storage moves to **R2**.
3. Qdrant connection follows the **graph-rag Cloud-style configuration**.
4. Retrieved payloads remain **compatible with `summarizer_project` downstream expectations**.
5. After VectorDB retrieval, execution continues through `summarizer_project/main.py` and its existing modules.

This keeps graph-rag as the priority on ingest-side conflicts without breaking the downstream GraphRAG and summarization pipeline already present in `summarizer_project`.

## Existing Architecture

### `graph_rag-pipeline`

Relevant capabilities:

- Docling-oriented ingest direction (per user decision)
- Qdrant Cloud-style connection (`url` + `api_key`)
- R2-based image/object storage approach
- embedding model preference from graph-rag side

Observed constraint:

- the generic `src/pdf_pipeline.py` retrieval contract is thinner than `summarizer_project` needs downstream (`text`, `source`, `page`, `score` vs richer chunk payload).

### `summarizer_project`

Relevant capabilities to keep:

- `main.py` orchestration for retrieval onward
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

Current ingest-side conflicts:

- `preprocessing/docling_loader.py` uploads via `MinIOHandler`
- `storage/minio_handler.py` assumes MinIO local bucket semantics
- `vectordb/qdrant_handler.py` assumes local host/port Qdrant
- `upload_to_qdrant.py` drives the old summarizer-side ingest flow

## Target Architecture

### High-level flow

```text
Input PDF
  -> graph-rag Docling ingest flow
  -> chunk generation with downstream-compatible metadata
  -> embed with graph-rag-priority model/config
  -> upload image/object assets to R2
  -> store vectors + payloads in Qdrant Cloud-style backend
  -> retrieve chunks
  -> summarizer_project entity extraction onward
  -> graph analysis + summarization + evaluation
```

### Ownership boundaries

#### Graph-rag owns

- ingest behavior
- storage backend behavior
- Qdrant Cloud connection behavior
- infra-side conflicts where old summarizer ingest differs

#### Summarizer project owns

- retrieval-to-summary orchestration
- graph/entity logic
- ranking/pruning logic
- summarization logic
- evaluation and quality control

## Required Data Contract

The ingest/retrieval layer must preserve a payload shape that downstream `summarizer_project` can consume safely.

Minimum required fields:

- `chunk_id`
- `text`
- `level`
- `source`
- `page_no`
- `image_url`

Retrieval-time fields added or preserved:

- `score`
- `rank`

### Contract rules

1. `page_no` is the canonical page field for `summarizer_project`.
2. If graph-rag code uses `page`, the adapter normalizes it to `page_no`.
3. `image_url` must point to R2-hosted assets, not MinIO URLs.
4. `level` must remain available even if graph-rag’s raw pipeline would otherwise omit it.
5. `chunk_id` must be stable enough for downstream entity extraction and graph-building stages.

## Design Changes by Area

### 1. `summarizer_project/upload_to_qdrant.py`

Change from “old summarizer ingest entry point” to “wrapper over graph-rag-priority ingest pipeline”.

Responsibilities after change:

- load runtime config,
- invoke the graph-rag Docling ingest path,
- ensure payload normalization into summarizer-compatible schema,
- upsert into Qdrant using the new backend config.

This file remains the local entry point so existing operator workflow stays simple.

### 2. `summarizer_project/preprocessing/docling_loader.py`

Keep only if it remains part of the graph-rag-priority Docling flow or as an adapter boundary.

Expected direction:

- remove active dependence on MinIO,
- route image/object upload through the new R2 storage layer,
- preserve or reconstruct downstream-required metadata,
- keep Docling-derived structure because the user explicitly chose Option B.

### 3. `summarizer_project/storage/`

Replace active MinIO usage with an R2-backed handler.

Requirements:

- S3-compatible upload interface,
- public URL builder aligned with R2 public base URL,
- bucket/container existence checks only if meaningful for R2 usage,
- no downstream callers should need to know whether the backend is MinIO or R2.

The old `MinIOHandler` should no longer sit in the live ingest path.

### 4. `summarizer_project/vectordb/qdrant_handler.py`

Adopt graph-rag-priority connection semantics:

- prefer `QDRANT_URL` + `QDRANT_API_KEY`,
- keep collection creation logic aligned with actual embedding dimension,
- keep methods that return chunk-shaped dicts for downstream summarizer modules.

This is an infra migration, not a downstream API rewrite.

### 5. `summarizer_project/config/settings.py` and env template

Expected config changes:

- remove MinIO-first assumptions from the active path,
- add R2 config values,
- add Cloud-Qdrant config values,
- make embedding model and dimension consistent with the graph-rag choice,
- preserve toggles that matter to the summarizer pipeline after retrieval.

## Migration Strategy

### Phase 1 — Storage and DB infra swap

- Introduce R2-backed storage handler.
- Introduce Cloud-Qdrant configuration in `qdrant_handler.py`.
- Preserve current downstream method signatures.

### Phase 2 — Ingest flow takeover

- Repoint `upload_to_qdrant.py` to the graph-rag-priority Docling ingest path.
- Normalize payload fields to the summarizer contract.
- Ensure image URLs are emitted from R2.

### Phase 3 — Retrieval contract validation

- Verify `main.py` retrieval output still satisfies downstream graph/entity modules.
- Confirm on-demand page/image logic still makes sense after R2 migration.

## Risks

### 1. Payload mismatch

Biggest risk: graph-rag-native payloads are too thin for downstream summarizer logic.

Mitigation: treat normalization as a required adapter, not an optional cleanup.

### 2. Embedding dimension mismatch

If embedding model changes, existing Qdrant collections may become incompatible.

Mitigation: treat collection schema as versioned by embedding dimension; recreate or isolate collections when needed.

### 3. Page field drift

`page` vs `page_no` inconsistencies can break image attachment and downstream display.

Mitigation: canonicalize on `page_no` at the ingest boundary.

### 4. Hidden MinIO assumptions

Some paths may still assume MinIO URL shape or bucket behavior.

Mitigation: replace backend access through one storage abstraction and remove direct MinIO assumptions from live code.

### 5. Docling structure loss

If the wrong graph-rag path is used, structure metadata may collapse to flat chunks.

Mitigation: use the graph-rag **Docling** ingest path specifically, not the generic flat `pdf_pipeline.py` contract as-is.

## Testing Strategy

### Required verification

1. Ingest a sample PDF through the new path.
2. Confirm vectors land in the target Qdrant collection.
3. Confirm image URLs resolve to R2-hosted objects.
4. Run retrieval and inspect returned chunk dictionaries.
5. Verify `summarizer_project/main.py` can continue from retrieval onward without payload errors.

### Minimum assertions

- every retrieved chunk has `chunk_id`
- every retrieved chunk has `text`
- page field is normalized to `page_no`
- `image_url` exists where page assets were uploaded
- downstream entity extraction does not fail on missing expected keys

## Implementation Constraints

- Prefer the smallest diff that changes active ownership correctly.
- Do not rewrite graph/summarization logic.
- Do not keep MinIO in the active ingest path.
- Do not let graph-rag priority erase downstream-required metadata.
- Do not make retrieval output depend on ad hoc one-off field conversions scattered across modules.

## Recommended Implementation Shape

Use a **thin adapter** approach:

- one storage backend replacement,
- one ingest orchestration replacement,
- one retrieval payload normalization layer,
- no downstream graph/summarizer rewrites unless a contract bug forces it.

This is the shortest path that honors the user's priority rule while preserving the working value already present in `summarizer_project`.
