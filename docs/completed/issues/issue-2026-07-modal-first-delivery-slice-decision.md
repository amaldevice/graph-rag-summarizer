# Decision: first Modal delivery slice

**Status:** accepted
**Tracker:** [Decide: first Modal delivery slice and acceptance boundary](https://github.com/amaldevice/graph-rag-summarizer/issues/95)

## Decision

The first Modal delivery slice is **Ingest Run with GPU-capable remote compute**.
The operator invokes it as a one-off `modal run` through a local controller;
the remote worker uses Qdrant Cloud and R2 while retaining the current
document-safe Ingest lifecycle.

## Boundary

- Include PDF staging, embedding on an explicitly selected CUDA-capable Function,
  Qdrant Cloud writes, R2 graph authority, Modal Secrets, and durable ordinary
  run artifacts.
- Preserve ADR 0001: `profile=cloud` remains the Qdrant Cloud/R2 pairing.
- Preserve ADR 0002: the existing runner owns reservation, claim, fence,
  generation, manifest, and idempotency behavior.
- Exclude Query-Only GPU and Full-Pipeline GPU from this slice. Query-Only may
  later use a deployed CPU Function when an endpoint or measured latency need
  exists; Full-Pipeline follows after artifact, retry, and timeout behavior is
  validated.

## Rationale

Ingest batches many chunk embeddings, so GPU benefit is measurable. Query-Only
mostly performs one embedding plus Qdrant I/O, while Full-Pipeline is materially
CPU/network-bound by graph work and external LLM providers.

## Next evidence

[Task: validate Modal Linux CUDA image and remote ingest safety](https://github.com/amaldevice/graph-rag-summarizer/issues/96)
must prove the remote image, persistent outputs, and document-safe retry path
before implementation is planned.
