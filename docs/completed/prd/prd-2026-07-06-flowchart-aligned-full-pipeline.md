## Problem Statement

The current Full-Pipeline Run already follows the broad GraphRAG summarization flow, but several flowchart-level behaviors are still simplified. Operators can ingest documents, retrieve chunks, build a graph, summarize communities, reduce to a final summary, evaluate quality, and write a feedback decision, but the run does not yet preserve true adaptive hierarchy through chunking, does not select context with path-aware reasoning, does not use explicit NAP/CAP/CGM prompt structure, does not reduce summaries through a RAPTOR-style multi-stage tree, does not report the requested grounded evaluation bundle, and does not automatically rerun the corresponding stage when the quality gate asks for it.

This leaves a gap between the intended research workflow and the current operator-facing behavior. A user looking at the flowchart expects one Full-Pipeline Run to produce a hierarchy-aware, graph-aware, quality-gated summary with bounded adaptive retry behavior, while the current implementation produces a simpler top-k graph summary and stops after writing the retry decision.

## Solution

Upgrade the Full-Pipeline Run so it closes the remaining flowchart-alignment gaps while preserving the existing launcher contract, Collection Target behavior, Launch Profile behavior, and Nomic/SBERT-compatible embedding path. The embedding model is not part of this change; the current Nomic embedding Stable Default is acceptable because the flowchart requirement is satisfied by a SentenceTransformer-compatible embedding runtime.

The improved run should preserve adaptive chunk hierarchy from Ingest Run through retrieval, use path-aware pruning over the graph, build explicit structure-aware prompts for node/community/global summarization, reduce summaries through a multi-stage RAPTOR-style aggregation path using the same embedding runtime, evaluate the final summary with a richer grounded quality bundle, and automatically retry the relevant stage within a bounded feedback loop when the quality gate requests retrieval, prompt, or reduction recovery.

The result should still feel like one normal Full-Pipeline Run to operators: same launcher surface, same core inputs, richer artifacts, and clearer quality decisions.

## User Stories

1. As an operator, I want the Full-Pipeline Run to match the intended flowchart behavior, so that the generated summary is produced by the expected research pipeline.
2. As an operator, I want to keep using the same launcher modes, so that flowchart alignment does not force me to learn a new entrypoint.
3. As an operator, I want the current Nomic/SBERT-compatible embedding path preserved, so that embedding behavior remains stable while the downstream pipeline improves.
4. As an operator, I want chunk hierarchy preserved during ingestion, so that later stages know whether context came from a sentence, paragraph, section, table, or figure-adjacent source.
5. As an operator, I want the Collection Target to store hierarchy metadata, so that retrieval can feed graph and summarization stages with structure-aware chunks.
6. As an operator, I want existing collections and payloads to remain readable, so that older ingested documents do not immediately break query-only or full-pipeline runs.
7. As a maintainer, I want chunk hierarchy represented as a small stable payload contract, so that graph, pruning, prompt, and evaluation code do not each invent their own schema.
8. As an operator, I want context selection to account for graph paths, so that summaries include evidence connected through important relationships instead of only isolated high-centrality chunks.
9. As an operator, I want global and per-community top-k context to remain bounded, so that prompts stay within practical LLM limits.
10. As a maintainer, I want path-aware pruning to produce inspectable artifacts, so that I can see why chunks were selected.
11. As an operator, I want prompt construction to explicitly use node-aware, community-aware, and global merge instructions, so that summarization follows the intended graph structure.
12. As an operator, I want prompt instructions to stay grounded in retrieved context, so that the LLM is discouraged from inventing unsupported claims.
13. As a maintainer, I want prompt behavior to be testable through produced prompt text and metadata, so that future prompt edits do not silently drop graph context.
14. As an operator, I want community summaries reduced through multiple levels when there are many communities, so that long-document runs do not rely on one oversized final prompt.
15. As an operator, I want reduction levels to use the same embedding runtime as retrieval, so that clustering and summary aggregation remain consistent with the run's Stable Defaults.
16. As a maintainer, I want RAPTOR-style reduction to degrade to a single merge for small runs, so that simple documents are not over-processed.
17. As an operator, I want final summaries to include enough evidence coverage, so that the output reflects the retrieved document rather than only a small subset.
18. As an operator, I want the evaluation layer to report factuality, consistency, LLM-judge, and QA-style coverage signals when available, so that quality decisions are easier to trust.
19. As an operator, I want unavailable evaluation metrics reported as unavailable rather than crashing the run, so that local setups without every optional evaluator still finish.
20. As a maintainer, I want quality decisions to explain which signal failed, so that the feedback loop can choose retrieval, prompt, reduction, or manual review appropriately.
21. As an operator, I want the feedback loop to automatically retry the relevant stage when safe, so that a failed quality check can recover without manually restarting the whole run.
22. As an operator, I want retry attempts bounded, so that the run cannot spin forever or burn unlimited provider calls.
23. As an operator, I want retry artifacts separated by attempt, so that I can compare the original and retried outputs.
24. As a maintainer, I want the existing Shared LLM Session behavior preserved across map summarization and final reduction, so that provider failover remains sticky within one run.
25. As a maintainer, I want the improved pipeline to reuse existing module seams where possible, so that this remains an evolution of the current project rather than a rewrite.
26. As a maintainer, I want tests to cover the Full-Pipeline Run at the launcher-runner seam, so that the user-visible behavior is protected end to end.
27. As a maintainer, I want focused module tests only where the logic is non-trivial, so that the test suite catches path selection, prompt construction, reduction levels, evaluator decisions, and retry state without overfitting internals.
28. As an operator, I want the final artifact directory to contain all new flowchart-alignment artifacts, so that one run remains easy to inspect.
29. As a maintainer, I want the new behavior to preserve Query-Only Run behavior, so that retrieval-only workflows stay lightweight.
30. As a maintainer, I want the new behavior to preserve Ingest Run automation, so that CI and scripts can keep driving ingestion non-interactively.

## Implementation Decisions

- Keep the current Nomic/SBERT-compatible embedding path. This PRD does not replace the embedding model with BGE-M3 or any other model; the flowchart should be considered updated to the current Nomic Stable Default.
- Preserve the single launcher contract. Flowchart alignment happens inside the existing Ingest Run and Full-Pipeline Run surfaces rather than adding a new Launcher Mode.
- Add a stable hierarchy-aware chunk contract. Chunks should carry enough structure for sentence, paragraph, section, and layout/table/figure-adjacent context while retaining backward-compatible defaults for older payloads.
- Keep object storage and vector storage behavior behind the existing Launch Profile and Collection Target boundaries. The change should not create separate local/cloud pipeline branches.
- Store hierarchy and layout metadata in retrieval payloads, and normalize missing values at the retrieval boundary so older collections can still run.
- Replace simple graph centrality pruning with a path-aware selector that can combine semantic relevance, graph centrality, relationship paths, and community boundaries while keeping top-k limits explicit.
- Produce inspectable selection artifacts that explain selected chunks, selected communities, path evidence, and ranking signals.
- Make NAP/CAP/CGM-style prompt structure the default prompt behavior for the improved Full-Pipeline Run. Avoid a new prompt-profile option unless a later user need requires it.
- Preserve the existing Shared LLM Session across map summarization and final reduction.
- Add a RAPTOR-style reducer path that can cluster or group community summaries across levels, re-embed intermediate summaries with the same embedding runtime, and stop early for small inputs.
- Add richer evaluation output with metric status fields. FactCC, SummaC, G-Eval, and QA coverage should be represented as named signals, but unavailable optional evaluators should produce explicit unavailable statuses instead of failing the run.
- Use the existing provider router for LLM-judge style evaluation where needed, so provider failover behavior remains consistent with summarization.
- Extend quality decisions from a flat pass/warn/fail gate into actionable decisions that map to retrieval, prompt, reduction, or manual-review recovery.
- Close the feedback loop inside the Full-Pipeline Run with bounded automatic reruns. A retry should start at the requested stage and rerun downstream stages only.
- Write per-attempt artifacts in the chosen artifact directory, while preserving the existing artifact names for the final accepted attempt where practical.
- Do not add new abstractions unless they remove duplication in the runner or make bounded retries possible. The preferred design is a small stage-result contract rather than a large pipeline framework.

## Testing Decisions

- The highest-value test seam is the existing Full-Pipeline Run runner seam. Extend the current fake-module tests to assert stage order, retry behavior, shared provider session reuse, and artifact paths without requiring live Qdrant, Docling, or provider calls.
- Ingest behavior should be tested through the existing Ingest Run and payload-normalization seams, verifying hierarchy metadata is produced, stored, and retrieved without breaking older payload shapes.
- Path-aware pruning should have small deterministic graph tests that assert selected chunks and path evidence from a fixed graph.
- Prompt behavior should be tested by asserting the external prompt contract: generated prompts include node-aware, community-aware, and global merge instructions plus selected evidence metadata.
- RAPTOR-style reduction should be tested with fake embeddings and fake LLM sessions, proving small inputs take the single-merge path and larger inputs create multiple levels.
- Evaluation should be tested through metric status objects and quality decisions, not through heavyweight live model calls.
- Feedback loop behavior should be tested with fake quality decisions that request retrieval, prompt, and reduction retries, proving attempts are bounded and rerun only the necessary downstream stages.
- Regression coverage should preserve existing Query-Only Run, Ingest Run, Full-Pipeline Run dispatch, artifact-directory behavior, and Shared LLM Session behavior.

## Out of Scope

- Replacing Nomic/SBERT-compatible embeddings with BGE-M3 or another embedding model.
- Adding a new launcher mode or replacing the single launcher contract.
- Changing Launch Profile semantics, credentials handling, or the local/cloud backend selection contract.
- Rebuilding legacy Qdrant collections automatically.
- Making every optional evaluator mandatory on every machine.
- Building a UI for visualizing graph paths or retry attempts.
- Changing relation extraction provider routing beyond what is needed for the existing Full-Pipeline Run.
- Solving document-safe ingest modes; that remains covered by the existing safe PDF ingest PRD.

## Further Notes

The first implementation should be conservative: evolve existing seams, keep artifacts inspectable, and prefer bounded behavior over a generic workflow engine. The biggest risk is overbuilding a pipeline framework; the smallest useful target is one improved Full-Pipeline Run that can demonstrate hierarchy-aware context, path-aware pruning, structured prompting, multi-stage reduction, richer evaluation, and bounded adaptive retry behavior.
