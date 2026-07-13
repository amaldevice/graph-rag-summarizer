# PRD — adaptive global graph construction, community discovery, and context selection

Date: 2026-07-11
Status: Finalized as the repo-local decision record for parent issue #44
Parent issue: https://github.com/amaldevice/graph-rag-summarizer/issues/44

## Problem Statement

The current Full-Pipeline Run is graph-aware, but the graph stage still depends on local extraction and fixed global constants. Relations are discovered inside one retrieved chunk at a time, broad co-occurrence fallback can connect every entity pair in a chunk with equivalent strength, chunk-similarity edges use one fixed neighbor count and threshold, Leiden accepts one fixed partition, and summary context uses fixed per-community and global top-k limits.

Those decisions are simple and bounded, but they are not adaptive to the evidence available in a particular query and Collection Target. They can miss supported cross-chunk relations, retain noisy entity cliques, fragment sparse documents, merge unrelated dense topics, accept unstable community boundaries, and spend prompt budget on redundant or weakly relevant chunks.

The Full-Pipeline Run also lacks one explicit lifecycle for weak or orphan graph regions. Operators cannot reliably distinguish an explicit relation from same-chunk co-occurrence, see which global candidates were considered, understand why a node remained isolated or was removed, compare alternative community partitions, or trace how context budget moved between communities.

PR #32 established the required foundation: hierarchy metadata, chunk-to-entity mention edges, path-aware pruning, RAPTOR-style reduction, grounded metric contracts, and bounded feedback reruns. The missing capability is the adaptive graph-control layer between retrieval and the existing summarization stages.

## Solution

Evolve the existing Full-Pipeline Run into a bounded, inspectable graph-construction and evidence-allocation pipeline without changing its Launcher Mode or operator-facing launch contract.

The improved graph stage will preserve local extraction evidence, canonicalize entity identities conservatively, classify weak and orphan regions, generate bounded cross-chunk relation candidates, verify candidates when that capability is available, weight and clean graph edges according to evidence strength, adapt semantic chunk connectivity to the retrieved evidence distribution, explore multiple community candidates, select one partition deterministically, and allocate a bounded context budget according to query relevance and marginal information gain.

Every adaptive decision will produce artifacts with resolved policies, scores, budgets, inclusion reasons, and rejection reasons. Query-relevant chunks remain protected even when entity or relation extraction is weak. Existing Query-Only behavior and downstream contracts remain unchanged, while Ingest may host an internal optional graph-artifact stage owned by ADR 0002; the existing community summarization, hierarchical reduction, evaluation, Shared LLM Session, Sticky Failover, and bounded feedback behavior continue to operate after the selected evidence is produced.

### Clarification / Exception

The existing launcher and operator contract, including Query-Only behavior, remains unchanged. Ingest may include an internal, optional graph-artifact stage, and ADR 0002 is the lifecycle authority for that stage. Stacked follow-on PRs #64 and #65, backed by planning issues #60 and #61, keep ownership of adaptive topology and query-time context allocation; ADR 0004 and ADR 0005 are only the intended files for those follow-on decisions.

## User Stories

1. As an operator, I want the Full-Pipeline Run to discover supported relations across retrieved chunks, so that evidence is not limited by arbitrary chunk boundaries.
2. As an operator, I want cross-chunk discovery to remain bounded, so that one run cannot compare every entity pair or create unlimited provider cost.
3. As an operator, I want a run to complete when global relation verification is unavailable, so that adaptive graph construction does not make optional provider capability mandatory.
4. As an operator, I want every relation edge to state how it was produced, so that I can distinguish explicit evidence from weak co-occurrence.
5. As an operator, I want every relation edge to identify its supporting chunks, so that I can inspect the evidence behind it.
6. As an operator, I want relation confidence and verification state recorded, so that graph edges are not treated as equally trustworthy.
7. As an operator, I want same-sentence, nearby-window, and same-chunk co-occurrence distinguished, so that weak proximity is not presented as an explicit semantic relation.
8. As an operator, I want weak co-occurrence to carry less graph weight than verified relations, so that noisy local cliques do not dominate communities.
9. As an operator, I want obvious entity surface variants normalized consistently, so that repeated evidence connects to one stable graph identity.
10. As an operator, I want original entity mentions preserved, so that canonicalization remains auditable.
11. As an operator, I want uncertain aliases left separate, so that aggressive normalization does not create false relations.
12. As an operator, I want canonicalization decisions and confidence written to artifacts, so that entity merges can be reviewed.
13. As an operator, I want weak, mention-only, relation-orphan, isolated, and query-protected graph elements classified, so that graph support is understandable before cleanup.
14. As an operator, I want to know which orphan regions received recovery candidates, so that global discovery is inspectable.
15. As an operator, I want rejected and insufficient-evidence candidates recorded, so that missing graph edges are explainable.
16. As an operator, I want unsupported entity noise pruned only after bounded recovery, so that cleanup does not run before the pipeline has searched for supporting evidence.
17. As an operator, I want query-relevant chunks protected from entity-based cleanup, so that weak NER does not remove useful retrieved evidence.
18. As an operator, I want semantic chunk connectivity to adapt to the retrieved score distribution, so that sparse and dense documents do not use the same unexamined threshold.
19. As an operator, I want semantic graph degree bounded, so that adaptive connectivity cannot create an uncontrolled dense graph.
20. As an operator, I want the chosen graph policy and resolved thresholds written to artifacts, so that topology is reproducible.
21. As an operator, I want the fixed graph policy retained as a baseline and fallback, so that adaptive behavior can be compared and safely disabled.
22. As an operator, I want Leiden to explore multiple bounded resolutions, so that one arbitrary partition is not accepted automatically.
23. As an operator, I want community candidates compared by graph quality, semantic coherence, size distribution, singleton rate, and stability, so that selection reflects document-specific evidence.
24. As an operator, I want the active community partition chosen deterministically, so that identical inputs and Stable Defaults produce repeatable results.
25. As an operator, I want rejected community candidates to include rejection reasons, so that the selected partition can be audited.
26. As an operator, I want an embedding-clustering comparison artifact, so that I can see whether graph communities agree with semantic grouping.
27. As an operator, I want embedding clustering to remain diagnostic at first, so that it cannot silently replace the graph path.
28. As an operator, I want community importance to account for query relevance and retrieval evidence, so that irrelevant communities do not consume equal prompt budget.
29. As an operator, I want important communities to receive more context when they contain more unique evidence, so that fixed per-community top-k no longer underfeeds rich communities.
30. As an operator, I want repetitive communities to stop receiving context when marginal information gain becomes low, so that prompts contain less duplicate evidence.
31. As an operator, I want relevant communities to receive bounded minimum coverage, so that a large community cannot consume the whole budget.
32. As an operator, I want the total selected context constrained by a token or conservative character budget, so that prompt size stays predictable.
33. As an operator, I want selected and rejected chunks to include per-signal scores and reasons, so that context decisions are explainable.
34. As an operator, I want existing path-quality signals consumed when available, so that adaptive budgeting can benefit from #40 without reimplementing path candidate scoring.
35. As a maintainer, I want relation evidence represented by one backward-compatible contract, so that legacy local relation records remain readable during migration.
36. As a maintainer, I want candidate budgets expressed as Stable Defaults, so that operators are not forced through new launcher prompts.
37. As a maintainer, I want adaptive graph policies expressed through small named contracts, so that experiments do not become a general workflow framework.
38. As a maintainer, I want deterministic synthetic graph fixtures, so that relation recovery, topology, and community selection regressions fail reliably.
39. As a maintainer, I want the Full-Pipeline Run seam to verify stage order, artifacts, fallbacks, and bounded work, so that operator-visible behavior is covered end to end.
40. As a maintainer, I want local algorithm tests only where behavior is combinatorial, so that tests do not overfit orchestration internals.
41. As a maintainer, I want the current embedding runtime reused for graph and clustering diagnostics, so that this feature does not introduce a second embedding contract.
42. As a maintainer, I want the current graph and clustering dependencies reused first, so that no mandatory dependency is added without evidence.
43. As a maintainer, I want Query-Only and the external launcher/operator contract unchanged, with the optional ingest graph-artifact stage allowed internally under ADR 0002 and query-time adaptive selection still remaining Full-Pipeline, so that adaptive graph work stays inside the Full-Pipeline Run.
44. As a maintainer, I want the existing Shared LLM Session, Sticky Failover, hierarchical reduction, evaluation, and bounded feedback behavior preserved, so that graph improvements do not regress downstream reliability.
45. As a maintainer, I want extraction availability and malformed-output handling to remain owned by #39, so that this PRD does not duplicate the extraction reliability slice.
46. As a maintainer, I want explicit path-candidate enumeration and reranking to remain owned by #40, so that this PRD does not duplicate PathRAG-grade scoring.
47. As a researcher, I want before-and-after graph and context diagnostics, so that improvements are measured rather than assumed.
48. As a researcher, I want tradeoffs among precision, coverage, cost, coherence, and explainability reported separately, so that one metric does not hide regressions in another.

## Implementation Decisions

- Preserve the profile-driven single launcher ADR. The internal optional ingest graph-artifact stage is owned by ADR 0002, while query-time adaptive graph/context behavior remains inside the existing Full-Pipeline Run; introduce no new Launcher Mode.
- Treat PR #32 as the baseline. Hierarchy metadata, mention edges, path-aware plumbing, RAPTOR-style reduction, grounded evaluation contracts, and bounded reruns are prerequisites rather than new scope.
- Keep extraction availability, spaCy-only fallback reporting, malformed local relation validation, and provider-mode observability in issue #39. Global graph verification will consume that validated availability seam instead of recreating it.
- Keep explicit path-candidate enumeration, path-quality scoring, selected path identifiers, and rejected-path reasons in issue #40. Adaptive context allocation may consume a normalized path signal when available but must work without it.
- Introduce one backward-compatible relation-evidence contract carrying relation endpoints, relation label, source, local or cross-chunk scope, confidence, evidence chunk identities, evidence type, and verification state. Legacy relations are normalized at the graph boundary.
- Replace equal-strength all-pairs co-occurrence with scoped weak evidence. Same-sentence, nearby-window, and same-chunk-only evidence receive distinct types and monotonically weaker default weights.
- Canonicalize entities conservatively before global candidate generation. Normalize case, whitespace, punctuation, and obvious surface variants; preserve original mentions and confidence; do not merge entities solely because embeddings are close.
- Classify graph support after the initial graph is built and before recovery. The classification includes strongly supported, weakly supported, mention-only, relation-orphan, isolated/noise-candidate, and query-protected evidence.
- Generate cross-chunk relation candidates through bounded triggers: shared canonical identity, semantic neighbors, shared graph neighbors, document hierarchy or section adjacency, weak/orphan recovery, and compatible entity types with evidence.
- Enforce per-entity, per-chunk, and total-run candidate budgets. Persist the trigger and supporting evidence for every candidate before verification.
- Make global verification optional, structured, and bounded. Each candidate resolves to accepted, rejected, or insufficient evidence with confidence and evidence chunk identities. Unavailable verification leaves candidates unapplied and does not fail the run.
- Apply accepted global relations with stronger weight than weak co-occurrence and retain their evidence metadata. Perform unsupported-noise cleanup only after recovery, while protecting query-relevant chunks.
- Add a semantic graph-policy contract with the current fixed k-nearest-neighbor threshold as baseline and fallback. The first adaptive policy uses mutual-neighbor evidence plus bounded minimum and maximum degree, with a data-dependent similarity cutoff derived from the retrieved score distribution.
- Persist the selected semantic graph policy, resolved cutoff, degree bounds, edge counts, connected components, and fallback reason.
- Explore a bounded set of Leiden candidates with a resolution-aware objective while retaining the current modularity partition as a baseline. Use deterministic seeds and cap the number of resolution and seed combinations.
- Evaluate community candidates with normalized graph quality, semantic coherence, stability, singleton/noise rate, size balance, query coverage, and evidence support. Select the active partition through a deterministic named policy and record rejection reasons for alternatives.
- Use stable canonical entity and graph-node ordering before community exploration so repeated runs do not inherit nondeterminism from set or insertion ordering.
- Use agglomerative clustering over existing chunk embeddings as the deliberate v1 comparison baseline because scikit-learn is already required. Defer HDBSCAN and K-Means experiments until this baseline produces evidence that another comparator is needed. Keep the path diagnostic-only and never let it silently replace Leiden.
- Score community importance with normalized query similarity, retrieval-score mass, graph importance, validated relation support, unique entity or claim coverage, and document-section diversity.
- Allocate one total context budget across relevant communities, guarantee bounded minimum coverage, and cap per-community allocation. Communities below a safe relevance floor may receive no budget when the decision is recorded.
- Select chunks by normalized relevance, graph support, relation support, optional path signal, and novelty. Use an MMR-like marginal-gain rule to reduce redundancy and stop when the budget is exhausted or gain falls below the resolved cutoff.
- Preserve query-protected chunks even when relation evidence is weak. Every selected and rejected chunk records per-signal values and an inclusion or rejection reason.
- Produce auditable artifacts for entity canonicalization, relation candidates, relation verification, graph support and edge diagnostics, orphan recovery, community candidates, community selection, embedding-cluster comparison, adaptive context budgets, and enhanced pruned context.
- Keep Full-Pipeline attempt diagnostics in the existing run directory so retrieval-triggered feedback reruns remain comparable. Persistent document graph artifacts use ADR 0002's object-storage path; do not create a second artifact root or a new operator-facing run lifecycle.
- Reuse existing graph, Leiden, embedding, and scikit-learn dependencies first. Any future dependency addition requires a separate evidence-backed decision.
- Prefer small contracts at existing graph, community, context-selection, and Full-Pipeline seams. Do not introduce a generic graph workflow framework.

## Testing Decisions

- The primary external seam is the Full-Pipeline Run runner. Use seam-focused test groups that keep the adaptive subsystem introduced by the current slice real while replacing unrelated retrieval, embedding outputs, optional provider calls, summarization, evaluation, and feedback side effects with deterministic fakes. Keep coverage for the internal optional ingest graph-artifact stage while leaving Query-Only and the external launcher/operator contract unchanged. Add one compact tiny-fixture regression with the graph, community, and context contracts together to prove handoffs without turning the suite into a broad live integration harness.
- Good tests assert observable graph, partition, context, and artifact contracts rather than private helper calls or exact internal class layouts.
- Extend the existing Full-Pipeline fake-module tests as prior art for artifact-directory routing, Shared LLM Session preservation, and bounded feedback reruns.
- Add focused relation-contract tests proving explicit, weak, local, and cross-chunk evidence remain distinguishable and legacy relation records normalize safely.
- Add deterministic canonicalization tests for case, punctuation, whitespace, preserved mentions, unresolved aliases, and false-merge protection.
- Add bounded candidate tests proving per-entity, per-chunk, and total budgets, trigger provenance, deterministic ordering, and no all-pairs expansion.
- Add verifier contract tests for accepted, rejected, insufficient, and unavailable outcomes without live provider calls. Provider availability and malformed local extraction validation remain covered by #39.
- Add synthetic graph tests for a noisy co-occurrence clique, an orphan entity with valid cross-chunk evidence, query-relevant relationless chunks, sparse and dense semantic neighborhoods, and graph cleanup protection.
- Add semantic graph-policy tests proving the adaptive policy respects degree bounds, persists resolved values, and falls back to the fixed baseline on unsupported inputs.
- Add multiresolution tests using graphs with two clear communities, bridge nodes, imbalance, singleton noise, and a resolution-limit scenario. Assert deterministic candidate reporting and selection policy, not one library-specific membership ordering.
- Add embedding-comparison tests proving agglomerative diagnostics are produced from existing embeddings and never replace the active partition automatically.
- Add adaptive-budget tests for query-aware community importance, minimum and maximum allocations, total-budget enforcement, redundancy reduction, marginal-gain stopping, and query-protected evidence.
- Add scope-boundary regression tests proving adaptive selection can consume an optional path signal without constructing path candidates, and global graph verification can consume #39's availability contract without owning provider-mode behavior.
- Preserve existing Query-Only and external launcher/operator contract tests unchanged. Full-Pipeline regressions must retain the current provider fallback, Shared LLM Session, hierarchical reduction, evaluation, and bounded retry behavior while allowing the internal optional ingest graph-artifact stage to remain covered.
- Live smoke verification is optional and separate from deterministic CI. When run, compare one small scientific PDF and one larger heterogeneous PDF using graph fragmentation, orphan recovery, candidate acceptance, community coherence, evidence redundancy, prompt budget, and final grounding artifacts.

## Out of Scope

- Importing or reproducing the full Microsoft GraphRAG or PathRAG frameworks.
- Building a general-purpose knowledge graph database or persistent graph service.
- Comparing every entity pair or every retrieved chunk pair with an LLM.
- Changing Preferred Provider selection, the Fallback Chain, or Shared LLM Session semantics.
- Reimplementing extraction availability, spaCy-only fallback observability, or malformed local relation validation from issue #39.
- Reimplementing explicit path-candidate enumeration, path reranking, selected path identifiers, or rejected-path reasons from issue #40.
- Replacing Qdrant, Docling, NetworkX, igraph, Leiden, or the current embedding runtime.
- Adding HDBSCAN, BERTopic, a tokenizer, or another mandatory runtime dependency before experiments justify it.
- Automatically merging entities only because their embeddings are similar.
- Removing all graph, community, or budget configuration parameters.
- Automatically deleting a query-relevant chunk because entity or relation extraction found no support.
- Changing Query-Only behavior or the external launcher/operator contract.
- Replacing existing community summarization, hierarchical reduction, evaluation, or feedback-loop contracts.
- Building a graph visualization UI or operator dashboard.

## Further Notes

- The rollout should remain incremental and artifact-first. Relation evidence and graph support must become observable before global recovery, and graph topology must become observable before adaptive community selection.
- The first useful milestone is not a claim of better summaries. It is a reproducible artifact trail showing why edges exist, which weak regions were considered, which candidates were accepted, and how the graph changed.
- Community quality metrics can disagree. The selection policy must therefore remain deterministic, named, and inspectable rather than hiding a single opaque aggregate score.
- Before-and-after indicators should include orphan count, accepted and rejected cross-relation rate, explicit-to-weak edge ratio, connected-component count, community stability, intra-community semantic similarity, singleton rate, selected-evidence redundancy, unique evidence coverage, and prompt budget by community.
- No single indicator is a release gate by itself. The desired result is a measured improvement in the tradeoff among relation precision, community coherence, evidence coverage, cost, and explainability.
- The proposed implementation slices are recorded separately so each issue can ship a narrow, testable vertical outcome while preserving this parent PRD as the long-lived decision record.
