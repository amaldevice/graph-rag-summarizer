# PRD — safe PDF ingest modes for shared Qdrant collections in graph-rag-summarizer

Date: 2026-07-05
Status: Implemented locally; GitHub issue #12 remains open until the delivery PR is merged.

## Problem Statement

The repository can already ingest one PDF into local or cloud Qdrant through the same upload entrypoint, but the current flow is only safe when each collection effectively holds one document at a time.

Today every processed PDF starts `chunk_id` from zero again, and Qdrant uses that value as the point ID during `upsert`. That creates two user-facing problems:

- appending a new PDF into an existing collection can overwrite earlier chunks instead of preserving them, and
- downstream retrieval and graph stages do not yet have a document-safe chunk identity contract for mixed-document collections.

From an operator perspective, that means the current system does not yet provide a safe, explicit answer to three common ingest intents:

- add a new PDF into an existing collection,
- replace one document inside an existing collection,
- or intentionally rebuild an entire collection.

This gap exists regardless of whether Qdrant runs locally or in the cloud.

## Solution

Keep the current upload entrypoint and current local/cloud backend selectors, but add one document-aware ingest contract for Qdrant.

The improved contract should:

- accept a document identifier for each ingest run,
- derive document-safe point identities so multiple PDFs can coexist in one collection,
- expose an explicit ingest mode for `append`, `replace-document`, and `replace-collection`,
- preserve the existing “new collection” workflow through `QDRANT_COLLECTION`,
- and return retrieval metadata that stays safe when one collection contains multiple documents.

The default behavior should be safe by default: appending must not silently overwrite an existing document.

## User Stories

1. As a local operator, I want to ingest a PDF into local Qdrant, so that I can build and test the pipeline without cloud dependencies.
2. As a cloud operator, I want to ingest a PDF into Qdrant Cloud through the same workflow, so that deployment behavior matches local behavior.
3. As a user, I want to keep using a new collection name when I want a fully separate corpus, so that I can isolate experiments without extra tooling.
4. As a user, I want to append a new PDF into an existing collection safely, so that one collection can hold multiple documents.
5. As a user, I want append mode to reject accidental document collisions, so that I do not silently overwrite previously ingested content.
6. As a user, I want to replace one document inside a shared collection, so that I can re-ingest an updated PDF without rebuilding everything else.
7. As a user, I want replace-document mode to leave other documents untouched, so that shared collections stay stable.
8. As a user, I want to intentionally rebuild a whole collection, so that I can run a clean full refresh when needed.
9. As a maintainer, I want local and cloud Qdrant to share the same ingest semantics, so that backend selection does not change user expectations.
10. As a maintainer, I want one document identifier contract, so that each ingest run can be tracked and managed predictably.
11. As a maintainer, I want document-safe point identities, so that Qdrant upserts no longer collide across PDFs.
12. As a maintainer, I want retrieved chunks to include document-aware metadata, so that downstream stages can reason about mixed-document results safely.
13. As a maintainer, I want chunk identity in downstream retrieval to stay unique across a shared collection, so that entity extraction and graph preparation do not collide on repeated per-document chunk numbers.
14. As a user, I want the original source filename to remain visible in metadata, so that retrieved chunks stay understandable to humans.
15. As a maintainer, I want the upload script to remain the main operator entrypoint, so that this feature does not require a second tool or admin service.
16. As a maintainer, I want the default mode to fail loudly on unsafe duplicate-ingest cases, so that the safe path is the easy path.
17. As a tester, I want targeted regression coverage for append, replace-document, and replace-collection behavior, so that collection-management regressions fail fast.
18. As a collaborator, I want the README and operator examples to explain each ingest mode clearly, so that future users do not need chat history to operate the system.
19. As an operator, I want clear warnings when page-image enrichment cannot fully resolve a mixed-document retrieval locally, so that retrieval still works even if image enrichment is partial.
20. As a maintainer, I want the first pass to stay script-driven and minimal, so that the feature solves the real ingestion problem without introducing unnecessary infrastructure.

## Implementation Decisions

- Keep the current upload workflow centered on a single script entrypoint rather than introducing a new ingestion service or admin UI.
- Keep `QDRANT_BACKEND` as the selector for local versus cloud Qdrant; the new feature must not fork into separate backend-specific workflows.
- Keep `QDRANT_COLLECTION` as the way to target a different collection. Creating a new collection remains a naming decision, not a separate ingest mode.
- Add one explicit ingest mode selector with three values: `append`, `replace-document`, and `replace-collection`.
- Add one explicit document identifier contract for each ingest run. The first pass may derive a safe default from the PDF input, but users must be able to override it.
- Generate Qdrant point identities from document identity plus per-document chunk order so multi-PDF collections do not collide.
- Preserve per-document chunk order as separate metadata instead of relying on it as the storage-level point identity.
- Return document-aware metadata during retrieval, including document identity plus a chunk identity that remains unique inside shared collections.
- Treat the original PDF filename as human-readable source metadata, not as the only stable storage identity.
- In `append` mode, refuse the ingest if the target collection already contains the same document identifier.
- In `replace-document` mode, delete only points belonging to the matching document identifier before uploading the new points.
- In `replace-collection` mode, intentionally recreate or clear the collection before uploading the new document set for that run.
- Keep the local/cloud behavior identical at the contract level even if the client initialization differs underneath.
- Limit the first pass to explicit single-run ingest behavior. Do not add bulk scheduling, background jobs, or a document management dashboard.
- Mixed-document page-image enrichment may remain best-effort in the first pass. Retrieval must still work even when a local PDF path is not available for every returned document.
- Prefer the shortest implementation path that makes shared-collection ingest safe without redesigning the summarization pipeline.

## Testing Decisions

- Good tests should verify observable ingest behavior, not internal implementation details.
- The highest seams are the upload entrypoint contract and the Qdrant handler public contract; test there before adding lower-level helper tests.
- Add regression coverage that proves two PDFs can coexist in one collection without overwriting each other in append mode.
- Add regression coverage that proves replace-document mode only touches the targeted document.
- Add regression coverage that proves replace-collection mode rebuilds the collection intentionally.
- Add retrieval-contract tests that confirm returned chunk metadata remains document-aware and safe for downstream graph preparation.
- Keep local/cloud behavior under the same test shape by using fake clients and contract assertions rather than live backend duplication in most tests.
- Use the existing Qdrant-handler and entrypoint tests as prior art for style and seam selection.
- Add one documentation-facing verification pass so README examples and env names stay aligned with the actual operator contract.

## Out of Scope

- Reworking the graph ranking, summarization, or evaluation algorithms beyond the metadata changes strictly required to make mixed-document retrieval safe.
- Adding a multi-document local PDF registry or asset catalog for perfect on-demand image rendering across every previously ingested source file.
- Building a web UI, dashboard, or long-running ingestion service.
- Automatic migration of legacy collections that were created with the old point-ID scheme; rebuilding those collections is acceptable in the first pass.
- Adding batch orchestration for many PDFs in one command.

## Further Notes

- The current gap is not only a storage overwrite problem; it also affects downstream chunk identity whenever one collection contains multiple documents.
- The safest first-pass default is `append` with explicit refusal on duplicate document identifiers.
- The existing local/cloud split is already good enough; the missing piece is document-safe collection management, not a new backend abstraction.
