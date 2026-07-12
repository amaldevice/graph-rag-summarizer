# Persist a document-scoped graph artifact during Ingest Runs

**Status:** Accepted  
**Date:** 2026-07-12

## Context

The current Full-Pipeline Run builds a graph after query retrieval. This repeats entity/relation extraction and graph construction for every query, limits relations to the retrieved chunk set, and makes community discovery query-specific by accident. The project already has document-safe Qdrant identities and object-storage profiles that can support a reusable graph lifecycle.

## Decision

Build and persist one graph per document during an Ingest Run. Keep query execution hybrid:

1. Ingest writes vectors and payloads to Qdrant.
2. Ingest builds the document graph from the same full-document chunks and embeddings.
3. Ingest uploads a versioned graph artifact to the active object storage profile.
4. Ingest updates the object-storage manifest only after artifact validation succeeds.
5. Query retrieves relevant chunks from Qdrant, loads the related document graph artifact, and creates only a temporary relevant subgraph/view.

The graph artifact contract is:

- one compressed `graph.json.gz` per document version;
- references to `document_id` and `chunk_uid`, not duplicated chunk text;
- nodes, edges, communities, raw relation evidence, and manifest metadata;
- immutable versions with one active manifest pointer per document;
- R2 for cloud and MinIO for local profiles;
- Qdrant may cache the active graph version but is not the pointer source of truth.

Raw relation evidence and the active graph are separate conceptual layers. Weak, rejected, or unverified candidates remain auditable without being allowed to dominate the active graph.

Graph construction is best-effort. Vector ingest remains usable when graph construction is partial or unavailable, with explicit graph status and an independent rebuild path. Existing collections can be backfilled from Qdrant payloads without re-embedding. Legacy points without `document_id` must be rebuilt/re-ingested; their document ownership is never guessed.

Community partitions are selected and persisted at ingest from a bounded deterministic policy. Query runs rank and filter those communities by query relevance and allocate context using a bounded budget, relevance, graph support, and novelty instead of fixed per-community/global top-k values.

## Alternatives rejected

- **Build the full graph after every query:** repeats expensive work and prevents reusable cross-chunk document relations.
- **Persist the first collection-global graph:** creates cross-document identity collisions and complicates incremental append/replace operations.
- **Use Neo4j as a required graph store:** adds operational and dependency cost before graph scale requires it.
- **Add Parquet/`pyarrow` immediately:** adds a dependency and format decision before artifact size is measured; compressed JSON is sufficient for the first version.
- **Fail vector ingest when graph construction fails:** reduces data availability and makes optional LLM/storage failures destructive to the ingest path.

## Consequences

Positive:

- Query latency and provider cost decrease because graph construction is reusable.
- Cross-chunk relations and document-wide communities can be discovered before any query exists.
- Graph decisions become versioned, inspectable, and rebuildable.
- Existing Qdrant and R2/MinIO infrastructure remains the storage contract.

Costs and constraints:

- Ingest becomes more expensive and may require bounded entity/relation processing.
- Graph artifacts need versioning, manifest lifecycle, status reporting, and backfill tooling.
- Query-time code must handle missing, partial, or stale graph artifacts safely.
- A collection spanning multiple documents still requires temporary in-memory graph composition for cross-document queries; no persistent cross-document graph is introduced yet.

## Related work

- Issue #12 — document-safe Qdrant ingest contract.
- Issue #44 — adaptive global graph construction parent PRD.
- Issue #57 — persistent document-scoped graph wayfinder map.
- Issue #58 — resolved persistent ingest graph contract and backfill lifecycle.
