# Proposed issue slices — adaptive global graph construction

Parent PRD: #44 — https://github.com/amaldevice/graph-rag-summarizer/issues/44

Status: Published as GitHub issues #45–#52.

Work the frontier: a ticket is ready when every item in **Blocked by** is closed. Every slice includes Full-Pipeline wiring, inspectable artifacts, and deterministic tests for its own behavior; there is no separate horizontal “integration” ticket.

## 1. #45 — Make relation evidence auditable and weaken co-occurrence edges

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/45

**What to build:** Make a Full-Pipeline Run distinguish explicit relations from same-sentence, nearby-window, and same-chunk co-occurrence. Every graph relation should carry backward-compatible evidence metadata, and weaker evidence should receive a lower resolved edge weight. Operators should be able to inspect why an edge exists without changing the launcher flow.

**Blocked by:** None — can start immediately.

- [ ] Existing local relation records normalize into one backward-compatible evidence contract.
- [ ] Relation artifacts distinguish source, local/cross-chunk scope, confidence, evidence chunks, evidence type, and verification state.
- [ ] The fallback no longer represents every entity pair as an equally strong semantic relation.
- [ ] Same-sentence, nearby-window, and same-chunk-only evidence receive distinct monotonically weaker default weights.
- [ ] Full-Pipeline artifacts expose relation evidence and resolved weights.
- [ ] Deterministic tests cover legacy records, explicit relations, and each weak co-occurrence level.
- [ ] Extraction availability and malformed local-output handling remain owned by #39.

## 2. #46 — Canonicalize entities and report weak or orphan graph regions

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/46

**What to build:** Canonicalize conservative surface variants across retrieved chunks, preserve original mentions, classify graph support, and emit an operator-readable report of strongly supported, weak, mention-only, relation-orphan, isolated/noise-candidate, and query-protected elements before graph cleanup changes anything.

**Blocked by:** #45 — relation evidence is required to classify support consistently.

- [ ] Case, whitespace, punctuation, and obvious surface variants receive stable canonical identities.
- [ ] Original mentions, canonicalization confidence, and unresolved aliases remain inspectable.
- [ ] Embedding proximity alone never merges two entities.
- [ ] Graph elements receive deterministic support classifications based on evidence strength, mention frequency, graph support, retrieval relevance, and query matching.
- [ ] Query-relevant chunks are marked as protected even when they have no recognized entity relation.
- [ ] Canonicalization and weak/orphan reports are written to the Full-Pipeline artifact directory.
- [ ] Tests cover safe merges, unresolved aliases, false-merge protection, support categories, and query protection.

## 3. #47 — Generate bounded cross-chunk relation candidates

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/47

**What to build:** Generate a small, deterministic set of cross-chunk relation candidates from canonical identities, semantic neighbors, shared graph neighbors, hierarchy or section adjacency, compatible entity types, and weak/orphan recovery. The run should report what it considered without applying unverified relations.

**Blocked by:** #46 — candidate triggers require canonical identities and support classifications.

- [ ] Candidate triggers are named and recorded with their supporting chunks and entities.
- [ ] Per-entity, per-chunk, and total-run Stable Default budgets prevent all-pairs expansion.
- [ ] Candidate ordering and budget truncation are deterministic.
- [ ] Weak/orphan regions can request recovery candidates without bypassing total budgets.
- [ ] Candidate artifacts include generated, deduplicated, and budget-rejected entries with reasons.
- [ ] No candidate is inserted into the active graph before verification.
- [ ] Tests cover every initial trigger, deduplication, deterministic ordering, and all budget levels.

## 4. #48 — Verify cross-chunk candidates and recover supported graph regions

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/48

**What to build:** Verify bounded global relation candidates through the validated extraction/availability seam from #39, apply only accepted relations with supporting evidence, report rejected and insufficient outcomes, and clean unsupported entity noise after recovery while preserving query-protected chunks.

**Blocked by:** #47 and #39.

- [ ] Verification returns accepted, rejected, or insufficient evidence with confidence and evidence chunk identities.
- [ ] Provider or verification unavailability leaves candidates unapplied and still allows the Full-Pipeline Run to complete.
- [ ] Accepted global relations carry stronger evidence weight than weak co-occurrence and preserve their provenance.
- [ ] Rejected, insufficient, and unavailable outcomes remain inspectable; malformed local extraction handling remains owned by #39.
- [ ] Unsupported entity noise is removed only after recovery and only with a recorded reason.
- [ ] Query-protected chunks are never removed solely because relation recovery failed.
- [ ] Candidate and verification calls remain bounded and attempt-scoped during feedback reruns.
- [ ] Tests cover accepted, rejected, insufficient, unavailable, bounded-call, cleanup, and query-protection behavior without live providers.

## 5. #49 — Build adaptive semantic chunk topology with bounded degree

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/49

**What to build:** Add a named semantic graph policy that keeps the current fixed k-nearest-neighbor threshold as a baseline while providing one deterministic adaptive policy based on mutual neighbors, the retrieved similarity distribution, and bounded minimum/maximum degree. Operators should see the selected policy and graph-shape consequences.

**Blocked by:** None — can start immediately because semantic chunk topology is independent of relation recovery.

- [ ] The fixed policy remains available as a backward-compatible baseline and fallback.
- [ ] The first adaptive policy uses mutual-neighbor evidence and a data-dependent cutoff.
- [ ] Minimum and maximum degree bounds prevent fragmentation and uncontrolled density.
- [ ] Stable Defaults control the policy without adding a Launcher Mode or interactive prompt.
- [ ] Artifacts report the selected policy, resolved cutoff, degree distribution, edge count, connected components, and fallback reason.
- [ ] Stable graph-node ordering makes repeated inputs deterministic.
- [ ] Synthetic sparse, dense, and degenerate fixtures verify degree bounds, topology changes, and fallback behavior.

## 6. #50 — Select stable communities from multiresolution Leiden candidates

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/50

**What to build:** Explore a bounded set of resolution-aware Leiden partitions over the recovered adaptive graph, score them with normalized graph and semantic signals, and choose one active partition through a deterministic policy with explicit rejection reasons.

**Blocked by:** #48 and #49 — partition selection should consume the recovered graph and adaptive semantic topology.

- [ ] The current modularity partition remains available as a baseline.
- [ ] Candidate resolutions and seeds are bounded and deterministic.
- [ ] Every candidate records objective, resolution, community count, size distribution, singleton rate, graph quality, semantic coherence, query coverage, and practical stability.
- [ ] The selector normalizes incomparable signals before combining them.
- [ ] Identical inputs and Stable Defaults choose the same active partition.
- [ ] Rejected candidates include explicit rejection reasons.
- [ ] Candidate and selected-partition artifacts are written per Full-Pipeline attempt.
- [ ] Synthetic graphs cover clear communities, bridge nodes, imbalance, singleton noise, disconnected input, and a resolution-limit scenario.

## 7. #51 — Compare graph communities with an embedding-clustering baseline

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/51

**What to build:** Produce an experimental agglomerative-clustering comparison from the existing chunk embeddings and explain agreement or disagreement with the active Leiden partition without changing the selected partition automatically. Agglomerative clustering is the deliberate v1 scope; other clustering baselines are deferred until this comparison produces evidence that they are needed.

**Blocked by:** #50 — the comparison requires an active graph partition.

- [ ] Agglomerative clustering reuses the existing embedding runtime and scikit-learn dependency.
- [ ] The comparison reports cluster count, noise/singleton behavior where applicable, coherence, and agreement with the active graph partition.
- [ ] Diagnostic failures degrade gracefully and do not fail the Full-Pipeline Run.
- [ ] The diagnostic path never replaces the active partition automatically.
- [ ] No HDBSCAN, BERTopic, or other mandatory dependency is added.
- [ ] Artifacts make the baseline configuration and comparison results reproducible.
- [ ] Tests cover agreement, disagreement, small-input fallback, and diagnostic unavailability.

## 8. #52 — Allocate query-aware context with diversity and bounded budgets

URL: https://github.com/amaldevice/graph-rag-summarizer/issues/52

**What to build:** Replace universal fixed per-community top-k selection with one total context budget allocated by community importance, then select non-redundant chunks by normalized relevance, graph support, relation support, optional path signal, and marginal information gain. Operators should see why every chunk and community received or lost budget.

**Blocked by:** #50 — adaptive allocation requires the selected community partition. #51 is diagnostic and does not block delivery.

- [ ] Community importance combines normalized query similarity, retrieval-score mass, graph importance, validated relation support, unique evidence coverage, and section diversity.
- [ ] Relevant communities receive bounded minimum coverage and no community can consume the entire total budget.
- [ ] Communities below the safe relevance floor may receive no budget only with a recorded reason.
- [ ] Selection respects a token budget or conservative character approximation and stops at exhaustion or low marginal gain.
- [ ] An MMR-like novelty signal reduces repeated evidence.
- [ ] Query-protected chunks remain eligible when graph relation signals are weak.
- [ ] Optional normalized path scores from #40 can be consumed without implementing path candidates or path reranking here.
- [ ] Enhanced context artifacts contain allocations, per-signal values, selected/rejected chunks, and inclusion/rejection reasons.
- [ ] Seam-focused runner tests keep the context allocator real while faking unrelated stages, plus one compact tiny-fixture regression proves the graph-to-community-to-context handoff.
- [ ] Regression tests preserve Query-Only and Ingest Runs plus Full-Pipeline provider fallback, Shared LLM Session, hierarchical reduction, evaluation, and bounded retries.

## Dependency graph

```text
#45 ──> #46 ──> #47 ──> #48 ──┐
                                ├──> #50 ──> #51
#49 ────────────────────────────┘       └──> #52

Issue #39 ───────────────────────> #48
Issue #40 ── optional normalized path signal ──> #52 (not a blocker)
```

## Testing seam

Use the Full-Pipeline Run runner as the primary external seam through seam-focused groups: keep the adaptive subsystem introduced by the current slice real and fake unrelated retrieval, embedding outputs, optional provider calls, summarization, evaluation, and feedback side effects. Add one compact tiny-fixture regression for graph-to-community-to-context handoffs, plus focused deterministic tests for relation evidence, canonicalization, candidate budgets, graph topology, community selection, and adaptive allocation where behavior cannot be proven through the runner seam alone.
