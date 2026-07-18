# Implementation: Interactive document ID and summary edit recovery

**Status:** ready to merge
**Trackers:** [#85](https://github.com/amaldevice/graph-rag-summarizer/issues/85), [#86](https://github.com/amaldevice/graph-rag-summarizer/issues/86)

## Scope

- Prompt for a stable document ID in pure interactive Ingest Run, with the
  filename-derived value as the default; an explicit `--document-id` stays
  authoritative.
- Make summary `n` reopen mutable wizard fields using current values as
  defaults while preserving every explicit CLI lock.
- Cover interactive Ingest, Query-Only, and Full-Pipeline edit paths without
  changing runner, Qdrant, or persistent-graph lifecycle behavior.

## Result

- Interactive Ingest now prompts for `Document ID` after the PDF and Ingest
  Mode. Enter retains the safe filename-derived default; an explicit
  `--document-id` is never prompted or overridden.
- Choosing `n` at a summary reopens non-CLI inputs with the resolved value as
  its default. Explicit CLI values remain locked. This covers Ingest inputs
  plus Query-Only and Full-Pipeline fields. Enter `-` for the optional
  Full-Pipeline PDF to clear a previously selected enrichment source.

## Verification

- Focused launcher tests: **58 passed**.
- Full suite: **375 passed**.
- `compileall` for `main.py` and `launcher`; `main.py --help`; `git diff --check`.
- Independent standards and spec review: approved after the optional-PDF clear
  path was added.
