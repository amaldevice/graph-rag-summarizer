# GraphRAG Summarizer Flow Resources

## Knowledge

- [Flowchart image](./assets/flow-project-flowchart.jpeg)
  Primary visual source for the application flow: PDF input, preprocessing, chunking, graph analysis, summarization, evaluation, and feedback.
- [Flow Project next-development handoff](./docs/handoff-2026-07-06-flow-project-next-development.md)
  Current branch status, partial blocks, follow-up issue links, and latest run evidence.
- [README](./README.md)
  High-level application purpose, launcher modes, ingest flow, summarize flow, and artifact locations.
- [Full pipeline runner](./launcher/runners.py)
  Source of truth for runtime stage order: retrieval, graph, pruning, summarization, reduce, evaluation, and feedback.
- [Docling loader](./preprocessing/docling_loader.py)
  Source of truth for PDF preprocessing and chunk metadata.
- [Graph builder and analyzer](./graph/graph_builder.py)
  Source of truth for chunk/entity graph construction.
- [Prompt builder and reducer](./summarizer/prompt_builder.py)
  Source of truth for NAP/CAP/CGM prompting and final reduction.
- [Evaluation and quality checker](./evaluation/evaluator.py)
  Source of truth for grounded metrics and pass/warn/fail decisions.

## Wisdom (Communities)

- Internal project PR/issues: use PR #32 and issues #35-#43 for implementation tradeoffs and future work.
