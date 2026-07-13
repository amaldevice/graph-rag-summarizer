# Persist a document-scoped graph artifact during Ingest Runs

**Status:** Accepted
**Date:** 2026-07-13

## Context

Ingest Runs need one reusable, document-scoped graph-artifact lifecycle. The current Full-Pipeline Run still builds graph state after query retrieval, which repeats entity and relation extraction for every query and keeps persistence coupled to query-time execution.

This ADR owns only the persistent graph artifact, storage path, manifest lifecycle, status reporting, replacement safety, and backfill behavior. Adaptive topology and query-time context allocation are owned by stacked follow-on PRs #64/#65 and planning issues #60/#61.

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

`manifest_revision` is persisted in JSON. The object-store ETag is out-of-band storage metadata, not persisted JSON; readers and writers obtain the manifest bytes plus ETag from storage. Existing manifests publish with CAS/`If-Match`. When the manifest does not yet exist, writers create it with `If-None-Match:*`; if ETag support is unavailable they fall back to a collection-scoped lock or lease around the read-modify-write sequence. Stale writers must retry or abort; they must never overwrite a newer entry.

Each manifest entry contains:

- `document_id` — document identifier.
- `document_generation` — positive integer generation persisted in the Qdrant document payload and manifest entry.
- `source_fingerprint` — fingerprint for the source input that produced the bound graph.
- `artifact_digest` — SHA-256 digest of the canonical compressed artifact bytes; it may be null when no active artifact exists.
- `operation_id` — durable ingest operation identifier for the artifact build or backfill.
- `active_version` — the published artifact version; null when there is no active artifact.
- `active_artifact_key` — the published artifact pointer; null when there is no active artifact.
- `status` — the current artifact state.
- `backend` — the storage backend that owns the artifact bytes; it may be null when no active artifact exists.
- `previous_pointer` — the prior active pointer for this document; audit/recovery only and null when no prior active artifact exists.
- `updated_at` — last manifest update timestamp.
- `failure_reason` — optional diagnostic metadata for failures and rebuilds.

The artifact blob metadata carries the same `document_generation`, `source_fingerprint`, `artifact_digest`, and `operation_id`, and the manifest entry must match the artifact metadata exactly.

The pointer/status contract is explicit:

| Status | `active_version` / `active_artifact_key` | Reader authority | Generation / fingerprint match | Reader behavior |
| --- | --- | --- | --- | --- |
| `available` | Non-null | Authoritative | Must match current `document_generation` and `source_fingerprint` | Use the manifest entry |
| `partial` | Non-null | Not authoritative | May match current `document_generation` and `source_fingerprint`, but is visible only for diagnostics / optional inspection | Compatibility fallback |
| `pending` | Null | Not authoritative | Not yet published against current Qdrant data | Fallback |
| `stale` | Null | Not authoritative | Current Qdrant data no longer matches the in-flight or superseded graph | Fallback |
| `unavailable` | Null | Not authoritative | No usable active artifact exists | Fallback |

`pending` is written before Qdrant advances, with the active pointer null and the old pointer retained only in `previous_pointer`; while `pending` readers must fall back to the compatibility path.

`document_generation` is always a positive integer. All chunks for one ingest share the same generation. A new append starts at generation `1`; a replace increments the previous generation. Backfill with a valid `document_id` and no existing generation derives generation `1` from one consistent source fingerprint and writes it once; inconsistent or malformed payloads are unavailable/rebuild-required and are never guessed. `available` must match the current `document_generation` and `source_fingerprint`; `partial` may carry a non-null pointer but remains compatibility fallback and diagnostic-only; `pending`, `stale`, and `unavailable` always use compatibility fallback. If Qdrant has already been replaced but graph activation fails, the old pointer remains only as immutable/recoverable bytes in `previous_pointer`; the entry becomes `stale` or `unavailable`, the active pointer is cleared, and it must never remain falsely `available`.

The artifact key is exact and versioned:

- `graphs/{collection}/{document_id}/v{version}/graph.json.gz`

Replacement semantics are:

- `append` — create generation `1` for a new document; reject duplicate appends for an already-tracked `document_id`; publish only after validation succeeds.
- `replace-document` — CAS the manifest entry to `pending` with the new generation, null active pointer, and the prior pointer retained only in `previous_pointer` before any vector or artifact work, write the new artifact, then publish `available` or `partial` only after validation succeeds.
- `replace-collection` — apply the same document-level rules to each document; a failure for one document must preserve that document's prior artifact bytes and previous_pointer metadata, without treating the pointer as active.

Activation safety is:

- the manifest update must be atomic from the perspective of readers;
- stale writers must not overwrite a newer manifest pointer;
- immediately before publish, reread the Qdrant document metadata for the same `document_id` and verify that the expected `document_generation` and `source_fingerprint` still match; if they do not, reject publish, mark the entry `stale`, clear the active pointer, and keep the prior pointer only in `previous_pointer`;
- if replacement fails after Qdrant advances, mark the entry `stale` or `unavailable`, set `failure_reason`, clear the active pointer, and keep the prior pointer only in `previous_pointer`; the prior bytes remain immutable and recoverable through `previous_pointer`, but are not reader-active;
- the older validated artifact bytes remain immutable and recoverable through `previous_pointer` until a newer validated manifest is successfully published, but they are not reader-active while the entry is pending, stale, or unavailable.

Raw relation evidence and the active graph are separate conceptual layers. Weak, rejected, or unverified candidates remain auditable without being allowed to dominate the active graph.

Existing collections can be backfilled from Qdrant payloads without re-embedding. Backfill ownership belongs to this ingest-stage lifecycle. Normal ingest uses deterministic operation ids of the form `ingest:{collection}:{document_id}:{document_generation}:{source_fingerprint}` and writes the pending manifest entry before vector or artifact work starts. Backfill keeps its deterministic operation ids of the form `backfill:{collection}:{document_id}:{source_fingerprint}`. An entry with matching terminal `operation_id`, `document_generation`, and `artifact_digest` is already complete. If an artifact upload was interrupted, resume only when the digest is an exact match; otherwise allocate `max(existing_versions)+1`. Missing, inconsistent, or malformed payloads are unavailable/rebuild-required and are never guessed. Reruns resume per document and preserve already active matching entries. Legacy points without `document_id` must be rebuilt or re-ingested because document ownership is never guessed.

## Alternatives rejected

- **Build the full graph after every query:** repeats expensive work and prevents reusable cross-chunk document relations.
- **Persist the first collection-global graph:** creates cross-document identity collisions and complicates incremental append/replace operations.
- **Use Neo4j as a required graph store:** adds operational and dependency cost before graph scale requires it.
- **Add Parquet/`pyarrow` immediately:** adds a dependency and format decision before artifact size is measured; compressed JSON is sufficient for the first version.
- **Fail vector ingest when graph construction fails:** reduces data availability and makes optional LLM/storage failures destructive to the ingest path.
- **Bundle adaptive topology or query-time context allocation into this ADR:** those decisions are owned by stacked follow-on PRs #64/#65 and planning issues #60/#61, not this document.

## Consequences

Positive:

- Graph artifacts become versioned, inspectable, and rebuildable.
- Ingest owns artifact creation, validation, backfill, manifest activation, and replacement safety.
- Existing Qdrant and R2/MinIO infrastructure remains the storage contract.
- Query-Only and downstream behavior remain unchanged while the ingest-stage graph artifact stays optional.

Costs and constraints:

- Ingest becomes more expensive and may require bounded entity and relation processing.
- Graph artifacts need versioning, manifest lifecycle, status reporting, stale-write protection, and backfill tooling.
- Query-time code must continue to handle missing or stale graph artifacts through the existing compatibility fallback path; `partial` artifacts remain diagnostic-only and are never authoritative.
- A collection spanning multiple documents still requires temporary in-memory graph composition for cross-document queries; no persistent cross-document graph is introduced here.

## Related work

- Issue #12 — document-safe Qdrant ingest contract.
- Issue #44 — adaptive global graph construction parent PRD.
- Issue #57 — persistent document-scoped graph wayfinder map.
- Issue #58 — resolved persistent ingest graph contract and backfill lifecycle.
