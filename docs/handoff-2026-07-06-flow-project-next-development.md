# Flow Project — current development handoff

**Snapshot:** 2026-07-15
**Current baseline:** `main` after PR #78 / Issue #43

## Current state

The Full-Pipeline flow is delivered end to end. Ingest can optionally publish a
document-scoped persistent graph artifact; a Full-Pipeline Run reuses that
artifact when it is available and otherwise falls back to the compatibility
query graph or vector-only context. Query-Only remains retrieval-only.

Delivered foundations include:

- hierarchy expansion and tiny-sentence filtering (#37–#38);
- provider availability reporting and spaCy-only graph fallback (#39);
- persistent graph ingest, bounded relation recovery, adaptive topology,
  deterministic community selection, and adaptive context allocation
  (#45–#52);
- lightweight grounded evaluation metrics (#43), including source traceability
  and selected-evidence-only evaluation.

`./.venv/bin/pytest -q` passed **332 tests** for the merged #43 state. Live
provider/model smoke runs remain optional because they require configured
credentials and may download models.

## Remaining ready-for-agent backlog

| Priority | Issue | Scope | Why it remains |
| --- | --- | --- | --- |
| 1 | [#40](https://github.com/amaldevice/graph-rag-summarizer/issues/40) | PathRAG-grade path candidates and scoring | Current pruning consumes path evidence but does not enumerate, score, and explain explicit path candidates. |
| 2 | [#36](https://github.com/amaldevice/graph-rag-summarizer/issues/36) | Table and figure evidence | Layout metadata exists, but table/figure evidence is not first-class selected prompt context. |
| 3 | [#41](https://github.com/amaldevice/graph-rag-summarizer/issues/41) | Embedding-similar RAPTOR reduction groups | Multi-level reduction exists; grouping is still fixed batches. |
| 4 | [#42](https://github.com/amaldevice/graph-rag-summarizer/issues/42) | Forced-fail feedback smoke path | Retry stages are covered deterministically, but there is no explicit safe dev/test forcing seam. |
| 5 | [#35](https://github.com/amaldevice/graph-rag-summarizer/issues/35) | Optional SummaC/FactCC adapters | Lightweight metrics are shipped; heavier model-backed evaluators remain opt-in research work. |

## Recommended next slice

Start with **#40**. It is the only current backlog item already consumed as an
optional signal by adaptive context allocation, and it improves explainability
without changing the launcher contract or adding a dependency.

Keep this slice bounded:

1. Enumerate candidate paths only from retrieved/selected graph evidence.
2. Score candidates deterministically from existing retrieval, graph, length,
   and diversity signals.
3. Persist selected path IDs plus rejected-path reasons.
4. Keep current path-aware chunk scoring as the compatibility fallback.
5. Add synthetic graph tests; do not require a live provider or a new PathRAG
   framework.

## Contracts not to regress

- Do not change Query-Only behavior or the external launcher/operator flow.
- Treat the persistent graph artifact as optional: compatibility and
  vector-only fallbacks must stay observable and usable.
- Keep selected evidence as the source for summary evaluation; do not restore
  an explicit empty selection from raw retrieval chunks.
- Keep heavy evaluation models optional. Missing adapters must report
  `unavailable`, not fail a normal run.
- Preserve bounded retries, per-attempt artifacts, query-protected evidence,
  and deterministic tests.

## Useful references

- `CONTEXT.md` — canonical launcher and runtime vocabulary.
- `docs/ONBOARDING_STARTER_ARCHITECTURE.md` — current architecture and source
  map.
- `docs/adr/0002-persistent-document-graph-at-ingest.md` through
  `docs/adr/0005-query-time-adaptive-context-allocation.md` — accepted graph
  decisions.
- `docs/runbook-single-launcher.md` — operator contract.
- `docs/completed/handoffs/handoff-2026-07-13-persistent-graph-implementation.md`
  — completed PR A–D delivery record, not active work.
