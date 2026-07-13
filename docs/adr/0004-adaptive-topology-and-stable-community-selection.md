# Use adaptive document topology with stable community selection

**Status:** Accepted  
**Date:** 2026-07-13

## Context

The current graph builder uses one fixed semantic kNN count and similarity threshold for every document, then accepts one Leiden modularity partition without comparing alternatives. This can over-connect dense documents, fragment sparse documents, and produce community boundaries that are not visibly justified. Embedding clustering can provide a useful comparison, but it does not carry the graph's relation evidence and should not silently replace graph communities.

## Decision

Use an adaptive topology and deterministic community-selection policy per document:

- Default to mutual-kNN semantic edges with a similarity cutoff derived from the document's similarity distribution.
- Enforce minimum/maximum degree and graph-shape guardrails. Preserve the current fixed kNN/threshold policy as a baseline and safe fallback.
- Record resolved thresholds, degree bounds, edge counts, orphan counts, density, selected policy, and fallback reasons in graph artifacts.
- Keep Leiden as the authoritative partitioner. Explore a bounded set of resolution candidates and deterministic seeds; never target a fixed community count.
- Reject or penalize candidates using named guardrails for fragmentation, singleton/noise rate, empty communities, and severe size imbalance.
- Normalize modularity, semantic coherence, stability, and size balance before ranking candidates. Record candidate metrics, policy, tie-breaks, and rejection reasons.
- Measure stability by comparing multiple deterministic Leiden seeds with ARI/NMI. Do not perturb the graph in the first version.
- Use agglomerative clustering over existing chunk embeddings as a diagnostic comparison only. Defer HDBSCAN until evidence shows that irregular/noisy clusters require it.
- Persist the selected partition at ingest. Query runs rank/filter communities and create temporary views without rerunning Leiden.

## Alternatives rejected

- **One global kNN/threshold policy:** ignores document-specific similarity distributions.
- **Fixed target community count:** makes the partition fit an arbitrary number instead of the graph evidence.
- **Embedding clustering as the authoritative partition:** loses relation/evidence topology and can change the graph contract silently.
- **Run Leiden once with one seed:** provides no stability or candidate comparison signal.
- **Add HDBSCAN immediately:** adds dependency/configuration complexity before the existing agglomerative baseline produces evidence.
- **Rerun community detection for every query:** repeats ingest-time work and makes document community boundaries unstable across queries.

## Consequences

Positive:

- Sparse and dense documents can receive different semantic graph connectivity.
- Community count and boundaries become inspectable outcomes rather than hidden fixed assumptions.
- The selected partition is reusable across queries while query relevance remains a separate ranking concern.
- Embedding clustering can expose disagreement without changing the graph source of truth.

Costs and constraints:

- Ingest performs more graph evaluation and stores more diagnostic metrics.
- Adaptive defaults and guardrails require deterministic fixtures and representative smoke runs for calibration.
- A fallback policy must remain available when adaptive topology becomes too sparse or too dense.
- Stability metrics compare partition membership; they do not prove semantic correctness by themselves.

## Related work

- Issues #49–#51 — adaptive topology, multiresolution Leiden selection, and embedding-clustering diagnostics.
- Issue #44 — adaptive global graph construction parent PRD.
- Wayfinder ticket #60 — adaptive graph topology and stable community selection.
