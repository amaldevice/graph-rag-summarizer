# Persist a document-scoped graph artifact during Ingest Runs

**Status:** Accepted
**Date:** 2026-07-13

## Context

Ingest Runs need one reusable, document-scoped graph-artifact lifecycle. The current Full-Pipeline Run still builds graph state after query retrieval, which repeats entity and relation extraction for every query and keeps persistence coupled to query-time execution.

This ADR owns only the persistent graph artifact, storage path, manifest lifecycle, fencing, status reporting, replacement safety, and backfill behavior. Adaptive topology and query-time context allocation are owned by stacked follow-on PRs #64/#65 and planning issues #60/#61.

This is an internal, optional stage of Ingest. The external launcher/operator contract, Query-Only behavior, and downstream behavior remain unchanged.

## Decision

Add an internal optional graph-artifact stage to Ingest Runs without changing the external launcher or operator contract.

1. Ingest reserves and claims the pending manifest entry and version under the manifest fence before any Qdrant or artifact work.
2. Ingest writes vectors and payloads to Qdrant as before.
3. Ingest may build or refresh the document graph artifact from the same full-document chunks and embeddings.
4. Ingest writes the versioned artifact to `graphs/{collection}/{document_id}/v{version}/graph.json.gz`.
5. Ingest writes the active manifest to `graphs/{collection}/manifest.json` and atomically activates a validated artifact by updating the manifest entry for that document only after validation succeeds.
6. Query-Only and downstream behavior stay unchanged; any consumer that reads the manifest must continue to honor the existing compatibility path when no usable artifact exists.

The collection manifest is authoritative and stores one entry per document. Readers resolve the entry for a given `document_id` from `graphs/{collection}/manifest.json`, then follow that entry's active pointer.

The manifest includes collection-level concurrency metadata:

- `manifest_revision` — monotonically increasing manifest revision for writers.

`manifest_revision` is persisted in JSON. The object-store ETag is out-of-band storage metadata, not persisted JSON; readers and writers obtain the manifest bytes plus ETag from storage. Existing manifests publish with CAS/`If-Match`. When the manifest does not yet exist, writers create it with `If-None-Match:*`; if ETag support is unavailable they must use a collection-scoped fenced lock/lease around the read-modify-write sequence instead of a plain lock. Lock acquisition returns a monotonically increasing fencing token; every manifest write carries that token; the storage adapter rejects any write whose token is lower than the latest accepted token; expired holders cannot write. If the selected backend cannot provide conditional writes or enforce fencing tokens, the manifest update must fail closed and abort rather than proceed with an unsafe plain lock. Stale writers must retry or abort; they must never overwrite a newer entry. The normal `If-Match` / `If-None-Match` path remains unchanged.

If ETag-based CAS is unavailable, the fallback must be implementable with a durable per-collection lock record stored on the same object-storage backend at `locks/{collection}.json`, or an explicitly configured durable coordinator with the same guarantees. The lock record must be updated with conditional `If-Match` / `If-None-Match` semantics to issue monotonically increasing fencing tokens. Manifest write/CAS requests must carry the token as metadata, and the adapter must reject lower tokens atomically. If the backend or coordinator cannot provide both durable token issuance and token-enforced manifest writes, the operation must abort and fail closed. This fallback supplements, but does not replace, the normal ETag path.

The durable claim that reserves a pending entry also fences the data plane for the same document and collection. The claim consists of `operation_id`, `document_generation`, `source_fingerprint`, `pending_attempt_id`, `build_attempt_id`, `pending_version`, and the manifest-issued fence token. Every Qdrant upsert, update, delete, and cleanup batch must re-check that the same claim still owns the document before the batch starts and again before any destructive cleanup. Qdrant payloads and control records must carry the generation, attempt identity, and fence token. Stale, superseded, or expired workers abort immediately. If the backend cannot issue or re-check this fence, the operation fails closed.

Each manifest entry contains:

- `document_id` — document identifier.
- `document_generation` — positive integer generation persisted in the Qdrant document payload and manifest entry.
- `source_fingerprint` — fingerprint for the source input that produced the bound graph.
- `artifact_digest` — SHA-256 digest of the canonical graph JSON bytes; it may be null when no active artifact exists.
- `operation_id` — durable ingest operation identifier for the artifact build or backfill.
- `pending_operation_id` — current owning operation for a pending manifest entry; null when no operation is pending.
- `pending_generation` — generation claimed by the current pending operation; null when no operation is pending.
- `pending_source_fingerprint` — source fingerprint claimed by the current pending operation; null when no operation is pending.
- `pending_attempt_id` — unique attempt identifier for the current pending build attempt; null when no operation is pending.
- `next_version` — next artifact version reserved by the manifest for the document; null only when the entry has never been versioned.
- `pending_version` — artifact version reserved by the current pending operation; null when no operation is pending.
- `active_version` — the published artifact version; null when there is no active artifact.
- `active_artifact_key` — the published artifact pointer; null when there is no active artifact.
- `build_attempt_id` — unique attempt identifier for the final CAS/publish attempt; null unless an operation is in flight or recently finalized.
- `status` — the current artifact state.
- `backend` — the storage backend that owns the artifact bytes; it may be null when no active artifact exists.
- `previous_pointer` — the prior active pointer for this document; audit/recovery only and null when no prior active artifact exists. It is a structured recovery object containing `artifact_key`, `version`, `backend`, `artifact_digest`, and `document_generation`.
- `updated_at` — last manifest update timestamp.
- `failure_reason` — optional diagnostic metadata for failures and rebuilds.
- `tombstone_operation_id` — durable replace-collection operation identifier for a tombstoned entry; null unless the entry was tombstoned.


The artifact blob metadata may carry `document_generation`, `source_fingerprint`, `artifact_digest`, `operation_id`, `pending_operation_id`, `pending_generation`, and `pending_source_fingerprint` as provenance, but those fields never grant ownership. `operation_id` remains deterministic for idempotent operation identity; `pending_attempt_id` and `build_attempt_id` are unique per build attempt and are generated per attempt so a superseding retry gets a new attempt id while an interrupted, non-superseded resume reuses the same attempt id. Writers, resumers, and readers must gzip-decompress `graph.json.gz`, validate the canonical uncompressed bytes, and require the SHA-256 of those bytes to equal the manifest digest, blob metadata digest, and pointer digest; any mismatch means the artifact is not available and the operation fails closed. Qdrant persists only `document_generation`, `source_fingerprint`, and the fence-bearing control metadata; resume and publish authorization come from the current manifest CAS fields plus the caller's inputs, and the artifact metadata plus current Qdrant `document_generation`/`source_fingerprint` are validation-only checks. The canonical artifact bytes are deterministic: serialize the graph JSON with RFC 8785 JSON Canonicalization Scheme rules as UTF-8, with deterministic key ordering and number/string normalization and no NaN/Infinity, then gzip the canonical bytes only for transport with fixed compression level, `mtime=0`, and an empty filename. `artifact_digest` is the SHA-256 of the canonical uncompressed graph JSON bytes, and state-artifact metadata repeats that exact digest. PR A must include a fixture test proving identical canonical graph input yields identical bytes and digest, and differing graph input changes the bytes and digest.

The pointer/status contract is explicit:

| Status | `active_version` / `active_artifact_key` | Reader authority | Generation / fingerprint match | Reader behavior |
| --- | --- | --- | --- | --- |
| `available` | Non-null | Authoritative | Must match current `document_generation` and `source_fingerprint` | Use the manifest entry |
| `partial` | Non-null | Not authoritative | May match current `document_generation` and `source_fingerprint`, but is visible only for diagnostics / optional inspection | Compatibility fallback |
| `pending` | Prior active pointer when one exists; null on first-document pending/unavailable | Not authoritative | Not yet published against current Qdrant data | Compatibility fallback |
| `stale` | Prior active pointer when one exists; null on first-document pending/unavailable | Not authoritative | Current Qdrant data no longer matches the in-flight or superseded graph | Compatibility fallback |
| `unavailable` | Null on first-document pending/unavailable; otherwise prior active pointer stays as recovery-only bytes when one exists | Not authoritative | No usable active artifact exists | Compatibility fallback |
| `tombstoned` | Null | Not authoritative | Non-discoverable tombstone for a document omitted by replace-collection; active fields are cleared only after the newest recoverable pointer is preserved in `previous_pointer` | Skip document entirely; compatibility fallback and Qdrant tombstone deny record/control point |

When `active_artifact_key` is null, the active-entry `backend` and `artifact_digest` are null as well. For `tombstoned`, `active_version`, `active_artifact_key`, `backend`, and `artifact_digest` are all null, `pending_operation_id` / `pending_generation` / `pending_source_fingerprint` / `pending_version` are cleared, `document_generation`, `source_fingerprint`, and `next_version` are retained, `updated_at` is retained, and `failure_reason` carries the tombstone reason. A tombstoned entry is not merely unavailable or missing: it is intentionally non-discoverable and must be skipped by readers and compatibility fallback. Replace-collection also writes a durable Qdrant-side tombstone deny control point for omitted documents with deterministic point id `graph-control:tombstone:` + SHA-256 hex of `collection + NUL + document_id`. The control point is a zero-vector record carrying `graph_control_point=tombstone`, `document_id`, `graph_tombstoned=true`, tombstone `document_generation`, tombstone `tombstone_operation_id`, tombstone `tombstone_attempt_id`, fence token, and `tombstone_complete=true`. The writer must read the point back and verify the stored payload before considering the tombstone durable; if read-back is missing, mismatched, or incomplete, retry under the same fence or fail closed. Manifest tombstoned entries remain authoritative for normal state and the Qdrant deny record is the deny-safety net only. If manifest read/write or Qdrant deny-record read/write is unavailable, the operation must fail closed for that document or collection and never fallback on uncertainty. The Qdrant tombstone deny record may be cleared only by an explicit new `replace-document` CAS that assigns a fresh generation, fresh attempt id, and fresh fence token. If the entry was pending and still had a current active pointer in `active_version`, `active_artifact_key`, `backend`, and `artifact_digest`, that exact pointer must be promoted into `previous_pointer` before the active fields are cleared. If `previous_pointer` already exists, preserve the newest recoverable pointer so the tombstoned entry never loses its only recovery pointer.


`pending` is written only after the pending manifest entry and version have been claimed under the manifest fence, and only then may Qdrant work begin. The pending entry keeps the current prior pointer in `active_version`, `active_artifact_key`, `backend`, and `artifact_digest` for recovery/readers while remaining non-authoritative; first-document pending/unavailable has a null pointer. While `pending`, readers must fall back to the compatibility path. A pending manifest update records ownership only in the manifest by CASing `pending_operation_id`, `pending_generation`, `pending_source_fingerprint`, `pending_attempt_id`, and `pending_version`, and the same manifest fence issues the data-plane fence token that every Qdrant batch must recheck before upsert, update, delete, or cleanup. The finalizer must separately re-read the current Qdrant `document_generation` and `source_fingerprint` before publish or failure handling, and that reread is validation-only, not ownership. The same build attempt keeps the same `pending_attempt_id` / `build_attempt_id` across an interrupted but not superseded resume; a superseding retry must mint a new attempt id, and the old attempt id cannot finalize or continue Qdrant work. On every final publish or failure transition, the CAS predicate must include `operation_id`, `document_generation`, `source_fingerprint`, `pending_operation_id`, `pending_generation`, `pending_source_fingerprint`, `pending_version`, `pending_attempt_id`, `build_attempt_id`, and the current manifest ETag or fencing token; a superseded old attempt cannot publish or mark failure even if every other field still matches. This publish/failure CAS is separate from the stale-transition CAS used after a Qdrant mismatch. After a mismatch, the stale-transition CAS compares `operation_id`, `pending_attempt_id`, `build_attempt_id`, `document_generation`, `source_fingerprint`, `pending_version`, and the current manifest ETag or fencing token; if that CAS fails, do nothing. On successful publish, the new pointer replaces the retained recovery pointer and the replaced pointer becomes `previous_pointer`. If a newer operation supersedes the pending one, the older reservation/version is permanently burned, the older operation aborts, and it cannot resume or change status. Tombstoned entries are never rediscovered by stale work: resumers and finalizers must present the current manifest fencing fields for the same operation, and any future reintroduction of a tombstoned `document_id` must use a fresh replace-document generation plus CAS; append with the same `document_id` remains rejected.

`document_generation` is always a positive integer. All chunks for one ingest share the same generation. A new append starts at generation `1`; a replace increments the previous generation. Backfill with a valid `document_id` and no existing generation derives generation `1` from one consistent source fingerprint and writes it once; inconsistent or malformed payloads are unavailable/rebuild-required and are never guessed. `available` must match the current `document_generation` and `source_fingerprint`; `partial` may carry a non-null pointer but remains compatibility fallback and diagnostic-only; `pending`, `stale`, `unavailable`, and `tombstoned` always use compatibility fallback, and `tombstoned` entries are skipped as non-discoverable. Query-time compatibility graph/vector-only fallback must exclude tombstoned `document_id`s before selecting chunks, so tombstoned documents are never considered for retrieval. Legacy-point detection must scroll with offset until Qdrant returns `None`, validate every returned point, exclude any point with `graph_control_point` from legacy classification, and fail closed on any page, offset, or filter uncertainty. If Qdrant has already been replaced but graph activation fails, the old pointer remains only as immutable/recoverable bytes in `previous_pointer`; the entry becomes `stale` or `unavailable`, the active pointer is retained only as recovery bytes when one exists, and it must never remain falsely `available`.

Version allocation is immutable and ledgered: `version_ledger` is the durable monotonic history, not object listing. Every normal ingest append uses `v1` for a new document. Replace/refresh reserves `max(version_ledger.version)+1` under manifest CAS before any Qdrant work begins, records the reservation as `pending`, and never reuses a version for different bytes. On the first document, manifest CAS initializes `pending_version=1`, `next_version=2`, and the ledger entry for `v1` as pending. A pending reservation becomes `published` only after successful publish, `failed` on terminal failure, `superseded` when a newer fenced reservation burns it, and `burned` if the claim is lost after reservation but before publish. Existing manifests that predate `next_version` initialize it under CAS to `max(existing_versions)+1`, and `next_version` always increases monotonically across reservations.

The artifact key is exact and versioned:

- `graphs/{collection}/{document_id}/v{version}/graph.json.gz`

The `v{version}` segment is the operation's reserved `pending_version`; the final artifact key never uses any other version choice.

Replacement semantics are:

- `append` — reserve the pending manifest entry and `v1` under the manifest fence before any Qdrant or artifact work; reject duplicate appends for an already-tracked `document_id`; create generation `1` for a new document; publish only after validation succeeds.
- `replace-document` — reserve `pending_version=next_version` and the matching manifest claim under the manifest fence before any Qdrant or artifact work; record the new generation in the pending manifest entry, keep the prior pointer in the active fields for recovery while `pending` remains non-authoritative, then write the new artifact and publish `available` or `partial` only after validation succeeds.
- `replace-collection` — derive the incoming `document_id` set, apply the same document-level replacement rules only to included documents, and atomically write tombstoned entries for omitted documents in the active collection manifest by the same manifest CAS. Omitted documents become non-discoverable tombstones: their immutable artifact bytes and recovery metadata are retained for audit and recovery, but they must not remain active or reader-discoverable; if the current entry is pending and still carries an active pointer, promote that exact pointer into `previous_pointer` before clearing the active fields, and if `previous_pointer` already exists keep the newest recoverable pointer. For replace-collection, write the durable Qdrant tombstone deny control point and completion proof before deletion, then retry deletion only after the tombstone is durable; deletion or point updates may touch only points that belong to the owning `pending_attempt_id` / `build_attempt_id`, generation, and fence token, or the operation must be serialized by the durable fence. Retrieval and compatibility fallback must filter points/document_ids with `graph_tombstoned=true` plus tombstone generation/operation markers, and the deny record is the source of truth for exclusion. If manifest reads/writes or Qdrant deny-record read/writes fail and the system cannot prove a document is not tombstoned, query must fail closed for that document or collection rather than using fallback. Missing or unavailable graph fallback remains only for documents proven not tombstoned. The manifest tombstone remains authoritative for normal state, and the Qdrant deny record/control point is the outage-safe safety net when the manifest is unavailable.

Activation safety is:

- the manifest update must be atomic from the perspective of readers;
- stale writers must not overwrite a newer manifest pointer;
- replace/refresh must reserve the next version number under manifest CAS before any Qdrant work begins so the version cannot be reused by a different byte sequence; the reservation is `pending_version`, and the same operation may resume that reserved version only if it was interrupted without being superseded and the fencing fields still match;
- immediately before any publish or failure transition, reread the Qdrant `document_generation` and `source_fingerprint` for the same `document_id`, then perform one atomic manifest CAS/If-Match against the same `operation_id`, `document_generation`, `source_fingerprint`, `pending_operation_id`, `pending_generation`, `pending_source_fingerprint`, `pending_version`, `pending_attempt_id`, `build_attempt_id`, and current manifest ETag or fencing token; if that CAS fails, abort without changing status or ownership;
- the stale-transition CAS after a Qdrant mismatch must compare `operation_id`, `pending_attempt_id`, `build_attempt_id`, `document_generation`, `source_fingerprint`, `pending_version`, and the current manifest ETag or fencing token; if it fails, do nothing;
- replace-collection tombstones are written in the same manifest CAS that removes a document from the active set, and the tombstone retains immutable artifact bytes and recovery metadata while clearing the active pointer fields only after the newest recoverable pointer has been preserved in `previous_pointer`; write the Qdrant tombstone deny control point before deletion, retry deletion only after the tombstone is durable and read back cleanly, and fail closed if deletion still cannot complete or if the system cannot prove the document is not tombstoned;
- a stale operation cannot reintroduce a tombstoned entry because the resumer/finalizer must still match the current manifest fencing fields; any explicit future reintroduction uses a new replace-document generation and CAS, and append with the same `document_id` remains rejected;
- if the reread no longer matches the pending claim, reject publish, mark the entry `stale`, retain the prior pointer/bytes in the active fields for recovery, and keep the older pointer in `previous_pointer` only after a successful new publish has replaced it;
- if replacement fails after Qdrant advances, mark the entry `stale` or `unavailable`, set `failure_reason`, retain the prior pointer/bytes in the active fields for recovery, and never label the entry `available`; the prior bytes remain immutable and recoverable through the active fields and `previous_pointer` when a newer validated manifest is successfully published, but they are not reader-active;
- the older validated artifact bytes remain immutable and recoverable through `previous_pointer` until a newer validated manifest is successfully published, but they are not reader-active while the entry is pending, stale, or unavailable.

Raw relation evidence and the active graph are separate conceptual layers. Weak, rejected, or unverified candidates remain auditable without being allowed to dominate the active graph.


Existing collections can be backfilled from Qdrant payloads without re-embedding. Backfill ownership belongs to this ingest-stage lifecycle. Normal ingest uses deterministic operation ids of the form `ingest:{collection}:{document_id}:{document_generation}:{source_fingerprint}` and writes the pending manifest entry plus its version reservation before vector or artifact work starts. Backfill keeps its deterministic operation ids of the form `backfill:{collection}:{document_id}:{source_fingerprint}`. An entry is already complete only when it has terminal `available` status, a matching active pointer, an existing artifact, and matching metadata/digest. If an artifact upload was interrupted, resume only when the digest is an exact match, the same `pending_version` is still reserved, and the current manifest CAS fields plus the caller's inputs still authorize the pending claim; the current Qdrant metadata is then validation-only. Otherwise allocate `pending_version=next_version` and increment `next_version` under CAS. Existing manifests that do not yet have `next_version` initialize it under CAS to `max(existing_versions)+1`, and `next_version` remains monotonic across retries and supersessions. A superseded reservation is permanently burned; only an interrupted but not superseded matching operation may resume its exact `pending_version`. Missing, inconsistent, corrupt, or malformed payloads are unavailable/rebuild-required and are never guessed. `partial`, `pending`, `stale`, and `unavailable` resume or repair rather than complete. Reruns resume per document and preserve already active matching entries. Legacy points without `document_id` must be rebuilt or re-ingested because document ownership is never guessed. Legacy-point detection must scroll with offset until Qdrant returns `None`, validate every point, exclude any point with `graph_control_point` from legacy classification, and fail closed on any partial scan, missing page, or filter uncertainty.

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
- Query-time code must continue to handle missing, stale, or tombstoned graph artifacts through the existing compatibility fallback path; `partial` artifacts remain diagnostic-only and are never authoritative, and tombstoned entries are skipped as non-discoverable.
- A collection spanning multiple documents still requires temporary in-memory graph composition for cross-document queries; no persistent cross-document graph is introduced here.

## Related work

- Issue #12 — document-safe Qdrant ingest contract.
- Issue #44 — adaptive global graph construction parent PRD.
- Issue #57 — persistent document-scoped graph wayfinder map.
- Issue #58 — resolved persistent ingest graph contract and backfill lifecycle.
