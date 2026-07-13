# Allocate query context by community importance and marginal evidence

**Status:** Accepted  
**Date:** 2026-07-13

## Context

The current summarization flow selects a fixed number of chunks per community and a fixed global number of chunks. That gives every community equal prompt space even when some are irrelevant or repetitive, and it cannot express a predictable total evidence budget. Persistent ingest-time communities now provide reusable structure, but query relevance still has to decide which parts of that structure enter the prompt.

## Decision

Replace fixed per-community/global top-k selection with a bounded query-time allocator:

- Use a total character budget for evidence context in the first version. Count selected chunk text, parent context, path evidence, and relevant metadata; keep general prompt instructions outside this budget and apply a provider-token safety check after selection.
- Score community importance from query similarity, retrieval-score mass, graph support, verified relation support, unique evidence coverage, and section diversity.
- Reserve minimum coverage for relevant communities, distribute the remaining budget by normalized importance, and cap each community's maximum allocation.
- Select chunks using relevance, graph/relation support, optional path support, and marginal novelty. Stop when the budget is exhausted or additional evidence is redundant.
- Preserve query-protected chunks even when their community has weak graph support.
- For a missing or stale persistent graph, fall back to the existing query-time graph for compatibility. If that also fails, continue with vector retrieval and summarization without graph support.
- For multi-document queries, load each document artifact into a temporary namespaced in-memory view. Do not create persistent cross-document edges.
- Consume path-aware scoring when available. If unavailable, renormalize the remaining signals, record the missing status, and continue allocation.

## Alternatives rejected

- **Fixed `top_k_per_community` and `top_k_global`:** wastes prompt space on irrelevant or repetitive communities and underfeeds evidence-rich communities.
- **Token budget as the first contract:** requires provider/tokenizer-specific behavior; character budgeting is simpler and provider-agnostic for the current system.
- **Allocate by query relevance alone:** can over-select similar but repetitive evidence and ignore graph/relation support or section diversity.
- **Fail when graph or path scoring is unavailable:** would make migration and optional graph improvements disruptive to existing users.
- **Create persistent cross-document edges during query:** introduces identity collisions and changes the document-scoped graph contract.

## Consequences

Positive:

- Prompt evidence size becomes predictable.
- Relevant communities receive more context without allowing one community to consume the entire budget.
- Redundant evidence is reduced through marginal novelty selection.
- Query-time behavior remains compatible with existing collections and optional path scoring.

Costs and constraints:

- Allocation requires explainable scores and selected/rejected reasons in artifacts.
- Character budgets are an approximation of provider token limits and need a final safety check.
- Query-protected chunks can consume budget even when their community is weakly connected.
- Multi-document graph composition is temporary and must preserve document namespaces.

## Related work

- Issue #40 — optional PathRAG-grade path scoring signal.
- Issue #52 — adaptive context with diversity and bounded budgets.
- Issue #44 — adaptive global graph construction parent PRD.
- Wayfinder ticket #61 — query-time adaptive context allocation over persistent communities.
