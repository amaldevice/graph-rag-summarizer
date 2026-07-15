# Flow Project — current development handoff

**Snapshot:** 2026-07-15
**Current baseline:** `main` after PR #81 / Issues #40–#42.

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

PR #81 added explicit bounded path candidates and provenance (#40),
embedding-similar RAPTOR groups (#41), and a private test-only forced retry
seam (#42). Its full deterministic suite passes **339 tests**; no new
dependency or ordinary launcher option was added.

## Remaining ready-for-agent backlog

| Priority | Issue | Scope | Why it remains |
| --- | --- | --- | --- |
| 1 | [#36](https://github.com/amaldevice/graph-rag-summarizer/issues/36) | Table and figure evidence | Layout metadata exists, but table/figure evidence is not first-class selected prompt context. |
| 2 | [#35](https://github.com/amaldevice/graph-rag-summarizer/issues/35) | Optional SummaC/FactCC adapters | Lightweight metrics are shipped; heavier model-backed evaluators remain opt-in research work. |

## Recommended next slice

After PR #81 merges, start with **#36**. It promotes existing layout metadata
into first-class selected evidence without changing the graph or launcher
contracts.

Keep this slice bounded:

1. Keep table and figure evidence within the existing character-budget and
   prompt-safety contracts.
2. Preserve compatibility and vector-only fallback behavior.
3. Add deterministic fixture coverage; do not require a live provider.

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
