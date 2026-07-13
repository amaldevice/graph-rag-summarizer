# Persist a document-scoped graph artifact during Ingest Runs

**Status:** Accepted
**Date:** 2026-07-13

## Context

Ingest Runs need one reusable, document-scoped graph-artifact lifecycle. The current Full-Pipeline Run still builds graph state after query retrieval, which repeats entity and relation extraction for every query and keeps persistence coupled to query-time execution.

This ADR owns only the persistent graph artifact, storage path, manifest lifecycle, status reporting, replacement safety, and backfill behavior. Adaptive topology belongs to ADR 0004, and query-time allocation/selection belongs to ADR 0005.

This is an internal, optional stage of Ingest. The external launcher/operator contract, Query-Only behavior, and downstream behavior remain unchanged.

## Decision

Add an internal optional graph-artifact stage to Ingest Runs without changing the external launcher or operator contract.

1. Ingest writes vectors and payloads to Qdrant as before.
2. Ingest may build or refresh the document graph artifact from the same full-document chunks and embeddings.
3. Ingest writes the versioned artifact to `graphs/{collection}/{document_id}/v{version}/graph.json.gz`.
4. Ingest writes the active manifest to `graphs/{collection}/manifest.json`.
5. Ingest atomically activates a validated artifact by updating the manifest entry for that document only after validation succeeds.
6. Query-Only and downstream behavior stay unchanged; any consumer that reads the manifest must continue to honor the existing compatibility path when no usable artifact exists.

The collection manifest is authoritative and stores one entry per document. Readers resolve the entry for a given `document_id` from `graphs/{collection}/manifest.json`, then follow that entry's active pointer.

The manifest includes collection-level concurrency metadata:

- `manifest_revision` — monotonically increasing manifest revision for writers.
- `manifest_etag` — conditional-write token or equivalent compare-and-swap guard.

Readers ignore the revision metadata. Writers must read the current manifest, preserve all existing document entries, increment `manifest_revision`, and publish the new manifest with CAS/`If-Match` semantics. If the backend does not provide conditional put, writers must use a collection-scoped lock or lease around the read-modify-write sequence. Stale writers must retry or abort; they must never overwrite a newer entry.

Each manifest entry contains:

- `document_id` — document identifier.
- `document_generation` — the generation currently bound to the entry.
- `source_fingerprint` — fingerprint for the source input that produced the bound graph.
- `active_version` — the published artifact version; null only when `status` is `unavailable`.
- `active_artifact_key` — the published artifact pointer; null only when `status` is `unavailable`.
- `status` — the current artifact state.
- `backend` — the storage backend that owns the artifact bytes; null only before the first successful publish.
- `previous_pointer` — the prior active pointer for this document; null when no prior active artifact exists.
- `updated_at` — last manifest update timestamp.
- `failure_reason` — optional diagnostic metadata for failures and rebuilds.

The active pointer pair in each entry is the only authoritative reader reference to the active artifact for that document. If either `active_version` or `active_artifact_key` is null, readers must treat the artifact as unavailable and fall back to the existing compatibility path; `previous_pointer` is audit history only.

The artifact status values are:

- `pending` — a new Qdrant generation is being prepared; readers must fall back to the existing compatibility path.
- `available` — the artifact validated successfully and the active manifest entry matches the current document generation. Readers may use it normally.
- `partial` — the artifact exists, but one or more graph sub-stages or validations are incomplete; keep the artifact visible, but readers must fall back to the existing compatibility path for authoritative behavior.
- `stale` — the manifest entry points at an older generation or a graph replaced by a newer Qdrant generation; readers must fall back to the existing compatibility path.
- `unavailable` — no usable active artifact exists for the document version; readers must fall back to the existing compatibility path.

`available` and `partial` must match the current `document_generation`. `pending`, `stale`, and `unavailable` always use compatibility fallback. If Qdrant has already been replaced but graph activation fails, the old pointer remains only as audit/recovery history and must be marked non-authoritative with `stale` or `unavailable`; it must never remain falsely `available`.

The artifact key is exact and versioned:

- `graphs/{collection}/{document_id}/v{version}/graph.json.gz`

Replacement semantics are:

- `append` — create the first artifact for a new document without deleting prior versions; reject duplicate document append attempts for an already-tracked document_id; activate the new pointer only after validation succeeds.
- `replace-document` — write a new version for the target document_id and activate it only after validation succeeds; if activation fails, preserve the previous active pointer.
- `replace-collection` — reprocess each document in the collection using the same document-level rules; a failure for one document must not overwrite that document's previous active pointer.

Activation safety is:

- the manifest update must be atomic from the perspective of readers;
- stale writers must not overwrite a newer manifest pointer;
- if a new artifact write or replacement fails after the artifact is written, the previous active pointer remains the source of truth;
- the older validated artifact stays active until a newer validated manifest is successfully published.

Raw relation evidence and the active graph are separate conceptual layers. Weak, rejected, or unverified candidates remain auditable without being allowed to dominate the active graph.

Existing collections can be backfilled from Qdrant payloads without re-embedding. Backfill ownership belongs to this ingest-stage lifecycle. Backfill uses deterministic operation ids of the form `backfill:{collection}:{document_id}:{source_fingerprint}` and per-document versioning of `max(existing_versions)+1`. Safe reuse is allowed only when the exact artifact digest and operation have already completed. Missing or malformed manifest entries are treated as unavailable and rebuilt; document ownership is never guessed. Reruns resume per document and preserve already active matching entries. Legacy points without `document_id` must be rebuilt or re-ingested because document ownership is never guessed.

## Alternatives rejected

- **Build the full graph after every query:** repeats expensive work and prevents reusable cross-chunk document relations.
- **Persist the first collection-global graph:** creates cross-document identity collisions and complicates incremental append/replace operations.
- **Use Neo4j as a required graph store:** adds operational and dependency cost before graph scale requires it.
- **Add Parquet/`pyarrow` immediately:** adds a dependency and format decision before artifact size is measured; compressed JSON is sufficient for the first version.
- **Fail vector ingest when graph construction fails:** reduces data availability and makes optional LLM/storage failures destructive to the ingest path.
- **Bundle adaptive topology or query-time context allocation into this ADR:** those decisions belong to ADR 0004 and ADR 0005.

## Consequences

Positive:

- Graph artifacts become versioned, inspectable, and rebuildable.
- Ingest owns artifact creation, validation, backfill, manifest activation, and replacement safety.
- Existing Qdrant and R2/MinIO infrastructure remains the storage contract.
- Query-Only and downstream behavior remain unchanged while the ingest-stage graph artifact stays optional.

Costs and constraints:

- Ingest becomes more expensive and may require bounded entity and relation processing.
- Graph artifacts need versioning, manifest lifecycle, status reporting, stale-write protection, and backfill tooling.
- Query-time code must continue to handle missing, partial, or stale graph artifacts through the existing compatibility fallback path.
- A collection spanning multiple documents still requires temporary in-memory graph composition for cross-document queries; no persistent cross-document graph is introduced here.

## Related work

- Issue #12 — document-safe Qdrant ingest contract.
- Issue #44 — adaptive global graph construction parent PRD.
- Issue #57 — persistent document-scoped graph wayfinder map.
- Issue #58 — resolved persistent ingest graph contract and backfill lifecycle.
