# Implementation: GPU-capable Modal Ingest Run

**Status:** resolved
**Tracker:** [Issue #98](https://github.com/amaldevice/graph-rag-summarizer/issues/98)
**Pull request:** [PR #97](https://github.com/amaldevice/graph-rag-summarizer/pull/97)

## Delivered slices

1. [#99](https://github.com/amaldevice/graph-rag-summarizer/issues/99) — added the thin `modal run` controller, PDF-byte staging, L4/CUDA remote Ingest, cloud-storage enforcement, named-Secret boundary, and committed Modal cache/run Volumes.
2. [#100](https://github.com/amaldevice/graph-rag-summarizer/issues/100) — preserved ADR 0002 graph ownership: the existing runner owns reservation, claim, fence, publish, R2 artifact, and manifest transitions. Provider exhaustion now uses bounded spaCy fallback and redacts provider diagnostics.
3. [#101](https://github.com/amaldevice/graph-rag-summarizer/issues/101) — made controlled `replace-document` retries remove obsolete document-control proofs as well as stale points, leaving only the active generation and control proof.

## Evidence

| Verification | Result |
| --- | --- |
| Final local suite | `uv run pytest -q` — **369 passed**. |
| Static diff | `git diff --check origin/main...HEAD` passed. |
| Independent review | Final re-review approved the credential-redaction and canonical durable-result fixes. |
| Remote Modal proof | NVIDIA L4, CUDA embedding, 732 source chunks, cloud Qdrant/R2, and graph artifact available. |
| Replacement proof | Fifth replacement for one document left generation 5, 733 document records, exactly one document-control point, zero stale records, and a readable R2 graph artifact. |
| Result durability | The persisted completion envelope reports a canonical `modal-volume://graph-rag-ingest-runs/artifacts/<run-id>` URI and graph-status URI, never a `/runs/...` worker path. |

## Operational follow-up

- The first slice intentionally leaves Query-Only Run and Full-Pipeline Run on their existing local path.
- Define a retention/cleanup procedure for staged PDFs in the Modal run Volume and a single-writer/warm-up policy for the shared model cache before higher-concurrency use.
- Early validation wrote a provider diagnostic to a historical stopped Modal run before redaction was added. Rotate the affected provider credential and treat old run logs as sensitive; no credential value is retained in this record.
- Disposable Modal proof collections, the test-only Secret, and Volume artifacts remain available as validation evidence; they were not deleted automatically.
