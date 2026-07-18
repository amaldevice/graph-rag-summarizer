# Implementation: Interactive document ID and summary edit recovery

**Status:** in progress
**Trackers:** [#85](https://github.com/amaldevice/graph-rag-summarizer/issues/85), [#86](https://github.com/amaldevice/graph-rag-summarizer/issues/86)

## Scope

- Prompt for a stable document ID in pure interactive Ingest Run, with the
  filename-derived value as the default; an explicit `--document-id` stays
  authoritative.
- Make summary `n` reopen mutable wizard fields using current values as
  defaults while preserving every explicit CLI lock.
- Cover interactive Ingest, Query-Only, and Full-Pipeline edit paths without
  changing runner, Qdrant, or persistent-graph lifecycle behavior.

## Verification

Focused launcher tests, complete suite, compile check, and final code review.
