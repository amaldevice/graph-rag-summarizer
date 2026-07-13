# Persist a document-scoped graph artifact during Ingest Runs

**Status:** Accepted  
**Date:** 2026-07-13

## Context

Ingest Runs need one reusable, document-scoped graph artifact lifecycle. The current Full-Pipeline Run still builds graph state after query retrieval, which repeats entity and relation extraction for every query and keeps graph persistence coupled to query-time execution. This ADR only defines the ingest-stage artifact lifecycle, storage, status, fallback, and backfill ownership. Adaptive topology and query-time context allocation are decided elsewhere in ADR 0004 and ADR 0005.

## Decision

Build and persist one graph per document version during an Ingest Run.

1. Ingest writes vectors and payloads to Qdrant.
2. Ingest builds the document graph from the same full-document chunks and embeddings.
3. Ingest uploads a versioned graph artifact to the active object-storage profile at `graphs/{collection}/{document_id}/v{version}/graph.json.gz`.
4. Ingest validates the artifact, then atomically advances the active manifest pointer only after validation succeeds.
5. Query may load the active artifact when it is `available`; it must surface `partial` or `unavailable` status and fall back to the existing compatibility path when no usable artifact exists.

The graph artifact contract is:

- compressed JSON at `graphs/{collection}/{document_id}/v{version}/graph.json.gz`;
- references to `document_id` and `chunk_uid`, not duplicated chunk text;
- nodes, edges, communities, raw relation evidence, and the artifact status for that version;
- an active manifest at `graphs/{collection}/{document_id}/manifest.json` with the fields `schema_version`, `collection`, `document_id`, `active_version`, `active_artifact_key`, `artifact_status`, `storage_backend`, `previous_active_version`, `previous_active_artifact_key`, and `updated_at`;
- immutable versions with one active manifest pointer per document;
- R2 for cloud and MinIO for local profiles;
- Qdrant may cache the active graph version but is not the pointer source of truth.

Raw relation evidence and the active graph are separate conceptual layers. Weak, rejected, or unverified candidates remain auditable without being allowed to dominate the active graph.

Graph construction is best-effort. The artifact status semantics are:

- `available` — the artifact validated successfully and the active manifest pointer matches the validated artifact version.
- `partial` — the document graph exists, but one or more graph sub-stages or validations are incomplete; keep the artifact visible, but do not treat it as fully authoritative.
- `unavailable` — no usable active artifact exists for the document version; query-time consumers must fall back to the compatibility path.

append, replace-document, and replace-collection behaviors all follow the same activation rule: write the new artifact version first, validate it, and then atomically replace the active manifest pointer. If replacement fails at any point after a new artifact is written, preserve the previous active pointer and leave the earlier validated artifact active.

Existing collections can be backfilled from Qdrant payloads without re-embedding. Backfill ownership belongs to Ingest Runs and the document artifact lifecycle; legacy points without `document_id` must be rebuilt or re-ingested because their document ownership is never guessed.

This ADR does not decide adaptive topology or query-time context allocation. Those choices remain owned by ADR 0004 and ADR 0005.

## Alternatives rejected

- **Build the full graph after every query:** repeats expensive work and prevents reusable cross-chunk document relations.
- **Persist the first collection-global graph:** creates cross-document identity collisions and complicates incremental append/replace operations.
- **Use Neo4j as a required graph store:** adds operational and dependency cost before graph scale requires it.
- **Add Parquet/`pyarrow` immediately:** adds a dependency and format decision before artifact size is measured; compressed JSON is sufficient for the first version.
- **Fail vector ingest when graph construction fails:** reduces data availability and makes optional LLM/storage failures destructive to the ingest path.
- **Bundle adaptive topology or query-time context allocation into this ADR:** those are separate decisions in ADR 0004 and ADR 0005, and duplicating them here would blur the lifecycle contract.

## Consequences

Positive:

- Query latency and provider cost decrease because graph construction is reusable.
- Cross-chunk relations and document-wide communities can be discovered before any query exists.
- Graph decisions become versioned, inspectable, and rebuildable.
- Existing Qdrant and R2/MinIO infrastructure remains the storage contract.
- Ingest owns artifact creation, validation, backfill, and manifest activation, which gives the graph stage one clear lifecycle boundary.

Costs and constraints:

- Ingest becomes more expensive and may require bounded entity and relation processing.
- Graph artifacts need versioning, manifest lifecycle, status reporting, and backfill tooling.
- Query-time code must handle missing, partial, or stale graph artifacts safely through the existing compatibility fallback path.
- A collection spanning multiple documents still requires temporary in-memory graph composition for cross-document queries; no persistent cross-document graph is introduced yet.

## Related work

- Issue #12 — document-safe Qdrant ingest contract.
- Issue #44 — adaptive global graph construction parent PRD.
- Issue #57 — persistent document-scoped graph wayfinder map.
- Issue #58 — resolved persistent ingest graph contract and backfill lifecycle.
