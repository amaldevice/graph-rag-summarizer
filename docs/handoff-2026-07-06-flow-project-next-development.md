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

## Remaining partials / yellow blocks

These blocks are implemented enough for the current project flow, but not full research-grade yet.

### 1. Preprocessing: table / figure / image handling

- **Tracking issue:** #36 — `Promote table and figure evidence into Full-Pipeline Runs`.
- **Why still partial:** Docling text/layout extraction is wired, but table/figure/image artifacts are not first-class summary evidence yet. On-demand image mode can also skip image export during ingest.
- **Step-by-step if implemented:**
  1. Define the minimal payload contract: `kind`, `page`, `bbox`, `caption`, `text`, optional `image_url`.
  2. Preserve table/figure chunks in Docling preprocessing.
  3. Store those fields in Qdrant payloads.
  4. Let pruning select table/figure evidence when it matches the query.
  5. Add prompt text that tells the LLM how to cite table/figure evidence.
- **Pros:** Better answers for PDFs where tables/figures carry key facts.
- **Cons:** More storage, slower ingest, and visual/table evidence can be noisy.
- **Effect on output:** Summaries can mention table/figure-backed facts instead of only body text.

### 2. Adaptive hierarchical chunking

- **Tracking issue:** #37 — `Build parent-child sentence paragraph section context expansion`.
- **Why still partial:** Current chunks carry hierarchy/layout metadata and can select `section`/`sentence`, but there is no clean parent-child tree from sentence → paragraph → section.
- **Step-by-step if implemented:**
  1. Add stable `parent_id`, `section_id`, and `path` metadata during ingest.
  2. Build paragraph nodes between sentence and section.
  3. Store all hierarchy IDs in Qdrant payloads.
  4. During retrieval/pruning, allow child hits to pull parent context.
  5. Test that a sentence hit can recover its paragraph/section context.
- **Pros:** Less fragmented context and fewer orphan sentence chunks.
- **Cons:** More ingest metadata and more retrieval expansion logic.
- **Effect on output:** Summaries become less choppy and have better local context.

### 3. Tiny sentence chunk filtering

- **Tracking issue:** #38 — `Filter tiny sentence chunks before summary pruning`.
- **Why still partial:** Sentence-level chunks are now active, so very short chunks like `Let Me.` can be selected.
- **Step-by-step if implemented:**
  1. Add a minimum word threshold in pruning, e.g. 8-12 words.
  2. Exempt `section` / title-like chunks from the threshold.
  3. Keep the filtered chunks visible in debug artifacts if needed.
  4. Add one test proving tiny sentence chunks are skipped.
- **Pros:** Smallest fix with clear summary-quality impact.
- **Cons:** Could drop meaningful short phrases if the threshold is too aggressive.
- **Effect on output:** Less filler, fewer weird one-line fragments in selected context.

### 4. Hybrid entity extraction

- **Tracking issue:** #39 — `Harden hybrid entity and relation extraction availability`.
- **Why still partial:** spaCy entity extraction works, but LLM relation mining depends on provider/API config. Without it, the graph is still useful but less semantically rich.
- **Step-by-step if implemented:**
  1. Make relation-extraction availability explicit in run artifacts.
  2. Keep spaCy-only graph generation as the fallback.
  3. Add a small relation schema check before adding LLM relations to the graph.
  4. Add tests for provider unavailable, provider available, and malformed relation output.
- **Pros:** Richer graph edges and better path evidence.
- **Cons:** Extra LLM cost, latency, and possible hallucinated relations.
- **Effect on output:** Path-aware pruning can choose more meaningful evidence paths.

### 5. PathRAG-grade pruning / reranking

- **Tracking issue:** #40 — `Upgrade path-aware pruning toward PathRAG-grade path scoring`.
- **Why still partial:** Current pruning is path-aware and records path evidence, but it is still heuristic. It is not a full PathRAG implementation with formal path enumeration and scoring.
- **Step-by-step if implemented:**
  1. Define path candidates from retrieved chunks through entity/relation/community nodes.
  2. Score paths with retrieval similarity, graph centrality, path length, and evidence diversity.
  3. Select chunks by best paths, not only best chunk scores.
  4. Persist selected path IDs and rejected-path reasons in artifacts.
  5. Add regression tests for path diversity and reranking order.
- **Pros:** More faithful to PathRAG and better multi-hop evidence selection.
- **Cons:** More graph traversal cost and harder-to-debug scoring.
- **Effect on output:** Better grounding for summaries that need relationships, not just similar chunks.

### 6. RAPTOR-style reduce grouping

- **Tracking issue:** #41 — `Group RAPTOR-style reductions by embedding similarity`.
- **Why still partial:** Multi-level reduction exists, but grouping is fixed batches, not embedding-clustered per level.
- **Step-by-step if implemented:**
  1. Embed community map summaries with the existing Nomic embedder.
  2. Group summaries by embedding similarity per reduction level.
  3. Reduce each group, then re-embed the intermediate summaries.
  4. Repeat until one final summary remains.
  5. Add tests with fake embeddings so grouping is deterministic.
- **Pros:** Related community summaries merge together first.
- **Cons:** More embedding calls and more complex deterministic testing.
- **Effect on output:** Final summaries should have cleaner thematic grouping and fewer abrupt topic jumps.

### 7. Evaluation layer: FactCC / SummaC and lightweight metrics

- **Why still partial:** The metric slots exist, but real adapters are not wired because FactCC/SummaC can add heavy dependencies, model downloads, and compatibility risk.
- **Tracking issue:** #35 — `Wire optional SummaC and FactCC grounded evaluation adapters`.
- **Lightweight metrics issue:** #43 — `Add lightweight grounded evaluation metrics without heavy models`.
- **Lightweight metric candidates:** entity consistency, number/date consistency, sentence evidence support, citation coverage, redundancy, query relevance, and evidence diversity.
- **Implementation order:** #43 is the cheaper first pass; #35 remains the heavier optional research-evaluator pass.
- **Step-by-step if implemented:**
  1. Keep `grounded_metrics.factcc` and `grounded_metrics.summac` keys stable.
  2. Add lazy optional adapters, starting with SummaC.
  3. Return `available` + normalized score when the evaluator runs.
  4. Return `unavailable` + clear reason when missing/disabled.
  5. Keep unavailable metrics as warnings in the quality gate.
  6. Add fake-adapter tests; do not require model downloads in CI.
- **Pros:** Better factual consistency signal than lexical overlap alone.
- **Cons:** Heavy, slower, and may be brittle on local Python/PyTorch setups.
- **Effect on output:** Quality reports can reject or retry summaries with unsupported claims.

### 8. Adaptive feedback loop live failure paths

- **Tracking issue:** #42 — `Add a forced-fail smoke path for adaptive feedback reruns`.
- **Why still partial:** Retry code exists for retrieval/prompt/reduce, but the latest live runs passed quality directly. The failure path is covered by unit behavior, not a forced live run.
- **Step-by-step if implemented:**
  1. Add a temporary/dev-only strict threshold or fake low metric for a smoke run.
  2. Run Full-Pipeline once and force a quality failure.
  3. Confirm the correct retry stage reruns.
  4. Compare attempt artifacts before/after retry.
  5. Remove or keep the dev-only trigger behind a clear test flag.
- **Pros:** Proves the feedback loop works in a real run.
- **Cons:** Costs LLM calls and can create noisy artifacts.
- **Effect on output:** More confidence that failed summaries self-correct instead of only reporting a decision.

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
