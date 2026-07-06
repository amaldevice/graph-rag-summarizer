# Issue slices — flowchart-aligned Full-Pipeline Runs

Parent PRD: #25 — https://github.com/amaldevice/graph-rag-summarizer/issues/25

## Published vertical slices

1. **#26 — Preserve hierarchy-aware chunks through Ingest and retrieval**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/26
   - Blocked by: None - can start immediately
   - User stories covered: 4, 5, 6, 7, 26, 27, 30
   - Scope: Make Ingest Runs emit and store backward-compatible hierarchy metadata, then make retrieved chunks expose that metadata to the Full-Pipeline Run.

2. **#27 — Select summary context with path-aware graph pruning**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/27
   - Blocked by: #26
   - User stories covered: 8, 9, 10, 17, 25, 28
   - Scope: Replace pure centrality top-k context selection with a bounded path-aware selector that includes selected path evidence in artifacts.

3. **#28 — Use NAP CAP CGM prompt structure in map and merge prompts**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/28
   - Blocked by: #27
   - User stories covered: 11, 12, 13, 24, 25
   - Scope: Make the default Full-Pipeline prompts explicitly node-aware, community-aware, and global-merge aware while preserving the Shared LLM Session.

4. **#29 — Reduce summaries through a RAPTOR-style multi-stage path**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/29
   - Blocked by: #28
   - User stories covered: 14, 15, 16, 17, 24, 28
   - Scope: Add a bounded multi-level reducer that groups community summaries, re-embeds intermediate summaries with the existing Nomic/SBERT-compatible runtime, and degrades to one merge for small runs.

5. **#30 — Report grounded quality with FactCC SummaC G-Eval and QA coverage signals**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/30
   - Blocked by: #29
   - User stories covered: 18, 19, 20, 26, 27, 28
   - Scope: Extend evaluation and quality decisions with named factuality, consistency, LLM-judge, and QA-coverage signals while treating unavailable optional evaluators as explicit statuses.

6. **#31 — Close the adaptive feedback loop with bounded automatic reruns**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/31
   - Blocked by: #30
   - User stories covered: 20, 21, 22, 23, 24, 26, 28
   - Scope: Make the Full-Pipeline Run rerun from retrieval, prompt, or reduction when the quality decision requests it, with bounded attempts and per-attempt artifacts.

## Testing seam

Use the existing Full-Pipeline Run runner seam as the main integration test seam, extending the current fake-module tests that already validate artifact paths and Shared LLM Session wiring. Add small module tests only for non-trivial local logic: hierarchy normalization, path-aware selection, prompt contract, multi-level reduction, evaluator status objects, and retry-state transitions.
