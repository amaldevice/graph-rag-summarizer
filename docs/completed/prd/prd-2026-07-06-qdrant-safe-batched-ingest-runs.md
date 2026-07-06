## Problem Statement

A hierarchy-aware Ingest Run can now produce many more chunks than the earlier paragraph-only flow. In the observed cloud run, Docling produced 6,634 chunks and embedding completed successfully, but the upload stage failed because the Qdrant Cloud JSON payload was about 110 MB while the service limit is about 32 MB per request. From the operator's perspective, the Ingest Run did almost all expensive work and then failed at the final upload step, leaving the new Collection Target created but not populated.

This blocks validating the flowchart-aligned Full-Pipeline Run against a freshly ingested Collection Target. Operators need large Ingest Runs to write vectors safely to Qdrant Cloud without changing the launcher workflow or manually splitting PDFs.

## Solution

Make Ingest Runs upload chunks to Qdrant in bounded batches instead of sending one all-at-once request. The public Ingest Run behavior should stay the same: choose a Launch Profile, choose Ingest Run, choose a PDF, choose a Collection Target, and let the run finish. Internally, the vector store writer should split the points into small enough batches, upload each batch in order, preserve the current payload contract, and report progress clearly enough that a failed run shows where it stopped.

The first implementation should be deliberately small: use one conservative default batch size, keep the existing launcher surface, avoid a new CLI option unless evidence shows operators need one, and add tests around the upload seam that failed.

## User Stories

1. As an operator, I want large Ingest Runs to upload successfully to Qdrant Cloud, so that hierarchy-aware chunking does not fail at the final step.
2. As an operator, I want to keep using the same launcher workflow, so that fixing upload size does not add a new mode or manual process.
3. As an operator, I want a new Collection Target to be populated after embedding completes, so that I can immediately run Query-Only or Full-Pipeline Runs against it.
4. As an operator, I want upload progress to show batches, so that I can tell whether a large ingest is still moving or where it failed.
5. As an operator, I want the current hierarchy/layout payload fields preserved, so that flowchart-aligned downstream stages still receive the richer chunk contract.
6. As an operator, I want older paragraph-sized ingests to keep working, so that the fix does not regress small PDFs or existing workflows.
7. As a maintainer, I want the fix at the vector store upload boundary, so that all Ingest Runs benefit without duplicating batching logic in the launcher.
8. As a maintainer, I want batch sizing to be conservative and boring, so that it avoids Qdrant Cloud request limits without a fragile byte-estimation system.
9. As a maintainer, I want upload failures to remain visible, so that a partial infrastructure failure is not silently treated as success.
10. As a maintainer, I want deterministic tests using a fake Qdrant client, so that the payload-limit fix does not need live cloud credentials in CI.
11. As a maintainer, I want the existing point and payload shapes preserved, so that retrieval and Full-Pipeline artifacts remain backward compatible.
12. As a maintainer, I want the implementation to avoid new dependencies, so that upload safety stays a small local change.
13. As an operator, I want the fixed run to work with the same Nomic/SBERT-compatible vectors, so that embedding behavior stays unchanged.
14. As an operator, I want the Collection Target name I selected to remain the destination for every batch, so that batched upload does not split data across collections.
15. As an operator, I want the final ingest count to still report the total uploaded chunks, so that I can confirm the full PDF was ingested.

## Implementation Decisions

- Keep the launcher contract unchanged. This is not a new Launcher Mode and should not require a new prompt, profile, or required CLI flag.
- Put batching at the Qdrant write boundary, because that is the shared seam that all Ingest Runs already use.
- Preserve the current point construction and payload normalization contract, including hierarchy, layout, source, page, and image URL fields.
- Use a conservative default batch size for point uploads. Avoid byte-size estimation and new configuration until there is evidence the fixed size is insufficient.
- Upload batches sequentially and fail fast on the first rejected batch. Do not pretend the run completed if Qdrant rejects a later batch.
- Keep collection creation behavior as-is. This PRD does not solve collection cleanup after a failed upload.
- Keep embedding behavior unchanged. The failure happened after embeddings were created, so embedding runtime and model selection are out of scope.
- Keep document-safe point IDs out of this PRD. That remains covered by the existing safe PDF ingest modes backlog.

## Testing Decisions

- Test the vector store upload seam with a fake Qdrant client that records each upsert call. The important external behavior is multiple bounded upsert calls for a large point set, not the private loop shape.
- Keep existing payload tests and extend them so batched uploads still preserve hierarchy/layout metadata and image aliases.
- Keep existing Ingest Run runner tests passing without changing the public runner contract.
- Add one regression test proving the upload path does not send all chunks in a single request when the chunk count exceeds the batch size.
- Do not use live Qdrant Cloud in automated tests. The observed cloud error is enough to identify the limit; CI should verify local batching behavior.

## Out of Scope

- Re-ingesting the user's PDF automatically.
- Deleting or repairing the partially created Collection Target from the failed run.
- Resumable uploads after a mid-batch failure.
- Dynamic byte-size payload estimation.
- New launcher prompts or CLI flags for batch size.
- Changing chunking, embeddings, retrieval, graph construction, summarization, or evaluation.
- Solving multi-PDF append/replace semantics or document-safe point IDs.

## Further Notes

The observed failure was not a Docling or embedding failure. It was a Qdrant Cloud request-size failure at upload time: one request attempted to send about 110 MB where the service accepted about 32 MB. The shortest reliable fix is to stop making one huge upload request.
