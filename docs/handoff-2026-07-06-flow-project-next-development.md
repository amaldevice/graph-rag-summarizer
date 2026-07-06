# Flow Project — next development notes

Date: 2026-07-06
Context: follow-up after the flowchart-aligned Full-Pipeline Run work in PR #32.

## Current answer

The project is now aligned with the flowchart end-to-end in a practical sense, but not every block is full research-grade yet.

The main gap from the earlier developer comment is addressed: the section after graph analysis is no longer just a quick placeholder. It now has path-aware pruning, structure-aware prompts, RAPTOR-style reduction, grounded metric statuses, and bounded feedback decisions.

## What is now improved after graph analysis

- **Pruning / reranking**
  - Before: mostly top-k centrality/composite score.
  - Now: path-aware scoring with path evidence, retrieval score, graph rank, hierarchy/layout metadata.

- **Prompting**
  - Before: simple structure-aware prompt.
  - Now: explicit NAP / CAP / CGM prompt instructions.

- **Map summarization**
  - Still one map summary per community.
  - Better because selected context now carries rank, hierarchy, and path evidence.

- **Reduce**
  - Before: one final merge.
  - Now: RAPTOR-style multi-level reduction when community count is larger than the group size.

- **Evaluation**
  - Before: ROUGE/BERTScore with reference, lexical overlap without reference.
  - Now: adds grounded metric objects for FactCC, SummaC, G-Eval, and QA coverage.
  - FactCC/SummaC are currently reported as unavailable unless real evaluators are configured.

- **Feedback loop**
  - Before: saved the suggested next stage only.
  - Now: can rerun from retrieval, prompt, or reduce within a bounded retry budget.

## Latest run evidence

Latest artifact checked:

```text
output/full_pipeline_2026-07-06T13-51-43-901349Z
```

Observed:

- Selected levels: `section` + `sentence`
- Path-aware pruning: enabled
- Path evidence: present on most selected chunks
- Reduction strategy: `raptor`
- Reduction levels: 2
- G-Eval: available, score around `0.86`
- QA coverage: available, score around `0.4375`
- Quality gate: PASS with warnings
- Warnings: FactCC and SummaC unavailable


## Flowchart status table

| Flowchart block | Current status | Notes |
|---|---:|---|
| Input Document | ✅ | PDF ingest works through the existing Ingest Run. |
| Preprocessing: text/layout/table/figure extraction | 🟡 | Docling extraction works and hierarchy/layout metadata exists. Table/figure handling is still basic; on-demand image mode may skip image export during ingest. |
| Adaptive hierarchical chunking | 🟡✅ | Latest re-ingest produced `section` and `sentence` selected chunks. Still not a clean parent-child hierarchy from sentence → paragraph → section. |
| Embedding | ✅ | Uses the current Nomic SentenceTransformer-compatible embedding path. This is accepted even though the flowchart text mentions BGE-M3/SBERT. |
| Vector DB storage + semantic retrieval | ✅ | Qdrant storage/retrieval works. Large uploads are now batched so hierarchy-aware ingest can fit Qdrant Cloud request limits. |
| Hybrid entity extraction | ✅/🟡 | spaCy extraction exists; LLM relation mining depends on provider/API configuration. |
| Hierarchical graph construction | ✅ | Graph includes chunk/entity nodes, KNN edges, relation edges, and mention edges. |
| Community detection | ✅ | Leiden-style community detection is wired and producing communities. |
| Graph analysis | ✅ | Centrality/ranking analysis is wired and produces ranked graph artifacts. |
| Pruning / reranking | 🟡✅ | Path-aware pruning and path evidence exist. It is still heuristic, not full paper-grade PathRAG. |
| Structure-aware prompt | ✅ | NAP / CAP / CGM instructions are explicit in prompts. |
| LLM summarizer map per community | ✅ | Community map summaries are generated. |
| Hierarchical reduce | 🟡✅ | RAPTOR-style multi-level reduction exists. Grouping is currently fixed batches, not embedding-clustered. |
| Evaluation layer | 🟡 | G-Eval and QA coverage are available. FactCC/SummaC are represented as unavailable statuses until real evaluators are wired. BERTScore remains reference-dependent. |
| Quality check | ✅ | Threshold-based quality gate runs and emits pass/warn/fail plus suggested action. |
| Adaptive feedback loop | 🟡✅ | Retrieval/prompt/reduce retry stages are implemented. Latest live runs passed directly, so failure-path retry needs a live forced-fail test if desired. |
| Final summary | ✅ | Final summary artifact is produced. |

## Remaining partials

These are the next useful improvements, in order:

1. **Filter tiny sentence chunks**
   - Problem: chunks like `Let Me.` can be selected because sentence-level chunking is now active.
   - Minimal fix: skip very short chunks during pruning unless `level == section`.
   - Suggested threshold: 8-12 words.

2. **Improve hierarchy model**
   - Current hierarchy metadata exists and works.
   - Still not a clean parent-child tree from sentence → paragraph → section.
   - Add only if downstream prompt/retrieval needs parent context.

3. **Make RAPTOR grouping embedding-aware**
   - Current reduction is multi-level but groups summaries in fixed batches.
   - Better version: cluster/group by embedding similarity per level.

4. **Add real FactCC/SummaC evaluators**
   - Current artifacts expose metric status fields.
   - Real models are not wired yet.
   - Add only if factuality evaluation is a real requirement.

5. **Live-test feedback loop failure paths**
   - Current retry code exists.
   - Latest runs passed quality directly, so live retry behavior has not been exercised with a failing quality gate.

## Recommendation

Next slice should be tiny-chunk filtering. It is the smallest change with the clearest quality impact.

Suggested issue title if promoted later:

```text
Filter tiny sentence chunks before path-aware summary pruning
```

Acceptance shape:

- Very short sentence chunks are not selected for summary context.
- Section/title chunks are still allowed even when short.
- Existing hierarchy/path-aware artifacts remain unchanged.
- Full test suite stays green.

## Notes for communicating status

Safe wording:

> The flow is now implemented end-to-end and the after-graph-analysis stages have been upgraded. It is aligned with the flowchart at a practical implementation level, but a few pieces remain minimal/heuristic rather than full research-grade: PathRAG scoring, RAPTOR grouping, FactCC/SummaC, and tiny sentence filtering.
