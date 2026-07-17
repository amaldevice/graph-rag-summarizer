# PRD: GPU-capable Modal Ingest Run

**Status:** ready for implementation
**Tracker:** [Implement: GPU-capable Modal Ingest Run](https://github.com/amaldevice/graph-rag-summarizer/issues/98)

## Problem Statement

An Ingest Run currently executes its PDF conversion, embedding, and optional
persistent graph stage on the operator machine. Launch Profile `cloud` selects
Qdrant Cloud and R2, but it does not select cloud compute. Operators with an
authenticated Modal account need a safe one-off GPU Ingest Run without copying
their `.env`, exposing a laptop path, or weakening the persistent document
graph lifecycle.

## Solution

Provide a thin `modal run` local entrypoint for an Ingest Run. It accepts the
same non-interactive Ingest inputs, stages the PDF for a remote Modal Function,
and receives a durable completion result. The remote Function runs the existing
Ingest lifecycle against Qdrant Cloud and R2 with credentials injected only by
a named Modal Secret.

The remote Function uses CUDA when it is available. Model cache and ordinary
run output may use committed Modal Volumes; R2 remains the authority for the
persistent graph artifact and manifest. A controlled retry must preserve
document-safe `replace-document` behavior.

## User Stories

1. As an operator, I want to invoke one GPU-capable Ingest Run with `modal run`, so that a large PDF does not depend on my local GPU.
2. As an operator, I want to keep Launch Profile `cloud` meaning Qdrant Cloud plus R2, so that compute placement does not silently change storage.
3. As an operator, I want the remote run to receive a staged PDF rather than my laptop path, so that it works in a Linux worker.
4. As an operator, I want CUDA selected only when the remote worker supports it, so that a CPU-only fallback is explicit and safe.
5. As an operator, I want model weights reused from durable cache, so that repeated Ingest Runs avoid needless downloads.
6. As an operator, I want Qdrant, R2, and provider credentials injected as a Modal Secret, so that secrets are not copied into an Image, request, or log.
7. As an operator, I want the remote run to report its resolved device and durable outputs, so that I can verify where the work ran.
8. As an operator, I want an optional graph artifact to retain its existing R2 manifest, claim, fence, generation, and idempotency rules, so that remote execution does not corrupt document state.
9. As an operator, I want two `replace-document` runs for the same document to leave one current document generation and no stale retrieval points, so that retrying is safe.
10. As an operator, I want a manifest backend mismatch to fail closed, so that an existing collection is never silently repaired or overwritten.
11. As an operator, I want ordinary run artifacts to be durable when reported, so that container-local paths are never presented as saved output.
12. As a maintainer, I want Query-Only Run and Full-Pipeline Run excluded from this first slice, so that the GPU Ingest boundary stays testable.

## Implementation Decisions

- Keep the interactive wizard and normal launcher process local. The first
  remote surface is a non-interactive one-off `modal run` entrypoint for an
  Ingest Run only.
- Treat Modal as an explicit compute backend. It is independent from Launch
  Profile; remote execution requires the cloud storage pairing rather than
  attempting to reach local Qdrant or MinIO.
- Reuse the existing Ingest runner and persistent graph pipeline. The Modal
  layer stages input, configures the worker, invokes the runner, and returns a
  serializable durable result; it does not recreate reservation or publication
  logic.
- Extend the embedding runtime contract with `cuda`. Linux `auto` chooses CUDA
  only when Torch reports an available GPU; explicit unsupported device choices
  retain a clear failure or supported fallback contract.
- Build the remote Image from locked project dependencies, include the spaCy
  language model needed by the optional graph stage, and put model cache on a
  named Volume.
- Stage source PDF bytes under a unique Volume key or use an existing approved
  object key. Materialize the source to worker-local scratch only while the
  run is active.
- Supply cloud credentials by a named Modal Secret only. Never serialize `.env`
  content, credentials, or a laptop path into the Image, request, return value,
  or progress log.
- Commit a Volume before returning any ordinary output stored there. Keep graph
  blobs and collection manifests on R2; a Modal Volume is never manifest or
  fencing authority.
- Default the first real proof to a fresh disposable Collection Target. Do not
  alter a collection whose manifest reports a different backend namespace.

## Testing Decisions

- Test the highest useful seam: the local Modal entrypoint produces the same
  validated non-interactive Ingest configuration used by the existing runner,
  while the remote boundary receives staged input rather than a local path.
- Extend the existing embedding runtime tests to prove CUDA selection, Linux
  auto-selection with and without an available GPU, and unchanged invalid
  device validation. Test behavior, not the implementation's Torch calls.
- Reuse the existing Ingest runner and persistent graph tests for document
  identity, reservation, generation, manifest, and replacement behavior; do
  not duplicate their lifecycle logic in Modal-only tests.
- Add a focused mocked Modal-boundary test proving that secrets and source data
  are referenced through the approved remote mechanisms and that a durable
  result contains no container-local output path.
- Run one authenticated remote smoke test on a disposable Collection Target:
  a PDF stages and converts, CUDA is the resolved embedding device, and Qdrant
  plus R2 are used.
- Run a second controlled `replace-document` Ingest Run with the same document
  ID. Verify the manifest generation, attempt and fence proof, graph artifact
  read-back, and retrieval excludes stale points. A backend namespace mismatch
  is a pass only when it fails closed without mutation.

## Out of Scope

- Query-Only Run on Modal, including a deployed query endpoint.
- Full-Pipeline Run on Modal, including LLM-provider placement, long-timeout
  orchestration, evaluation, and retry behavior.
- Changing Launch Profile semantics.
- Moving persistent graph manifest CAS, fencing, or artifact authority from R2
  to Modal Volume.
- Repairing or migrating an existing manifest with a backend namespace mismatch.

## Further Notes

Validation already proved a Modal Linux worker with an NVIDIA L4 and CUDA 13.0,
the locked project Image, PDF staging, Docling conversion, and direct GPU
embeddings. The direct 64-text microbenchmark measured 2.174 s CPU versus
0.036 s GPU after model load; it is not an end-to-end local comparison.

The implementation must preserve ADR 0001 and ADR 0002. The validation record
is `docs/completed/issues/issue-2026-07-modal-linux-cuda-validation.md`.

## Delivery Tickets

Work these in order:

1. [Implement: Modal GPU vector Ingest](https://github.com/amaldevice/graph-rag-summarizer/issues/99)
2. [Implement: Modal persistent-graph Ingest](https://github.com/amaldevice/graph-rag-summarizer/issues/100)
3. [Implement: Modal document-safe replacement](https://github.com/amaldevice/graph-rag-summarizer/issues/101)
