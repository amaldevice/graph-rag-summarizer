# Handoff: Persistent Document-Scoped Graph Implementation

Implementation handoff for the architecture route completed by Wayfinder. This document is an execution map, not a replacement for the PRD or ADRs.

## Mission

Move graph construction from repeated query-time work into a reusable, document-scoped artifact built during Ingest Runs, while keeping query-time retrieval, ranking, context allocation, and existing fallback behavior safe.

The destination is reached when a document can be ingested once, its graph can be reused across queries, existing collections can be backfilled without re-embedding, and the adaptive graph/context policies are observable and testable.

## Canonical references

Read these first; do not re-open the architecture decisions from scratch:

- [Issue #44 — adaptive global graph construction](https://github.com/amaldevice/graph-rag-summarizer/issues/44)
- `docs/prd-2026-07-11-adaptive-global-graph-construction.md`
- `docs/adr/0002-persistent-document-graph-at-ingest.md`
- `docs/adr/0003-bounded-global-relation-recovery.md`
- `docs/adr/0004-adaptive-topology-and-stable-community-selection.md`
- `docs/adr/0005-query-time-adaptive-context-allocation.md`
- [Wayfinder map #57 — closed](https://github.com/amaldevice/graph-rag-summarizer/issues/57)
- [Wayfinder decision #58 — closed](https://github.com/amaldevice/graph-rag-summarizer/issues/58)
- [Wayfinder decision #59 — closed](https://github.com/amaldevice/graph-rag-summarizer/issues/59)
- [Wayfinder decision #60 — closed](https://github.com/amaldevice/graph-rag-summarizer/issues/60)
- [Wayfinder decision #61 — closed](https://github.com/amaldevice/graph-rag-summarizer/issues/61)

The ADRs are currently carried by the stacked docs PRs [#62](https://github.com/amaldevice/graph-rag-summarizer/pull/62), [#63](https://github.com/amaldevice/graph-rag-summarizer/pull/63), [#64](https://github.com/amaldevice/graph-rag-summarizer/pull/64), and [#65](https://github.com/amaldevice/graph-rag-summarizer/pull/65).

## Current baseline

Current runtime behavior is:

```text
Ingest: PDF → Docling → chunks → embeddings → Qdrant
Query:  query → Qdrant retrieval → graph from retrieved chunks
        → Leiden → fixed top-k pruning → map/reduce → evaluation
```

The graph is currently assembled after retrieval. The current graph topology uses fixed semantic kNN/threshold behavior; Leiden runs once; context selection uses fixed per-community/global limits. The implementation route below replaces these seams incrementally rather than rewriting the launcher.

## Target architecture

```text
INGEST RUN
PDF
 └─ Docling: full-document chunks + hierarchy/layout/image metadata
    └─ stable document/chunk identities
       ├─ embed chunks
       │  └─ Qdrant: vectors + text/payload/document metadata
       ├─ extract entities and local relation evidence
       │  └─ raw evidence: source, confidence, support chunk IDs, status
       ├─ canonicalize/classify weak or orphan graph regions
       ├─ build active baseline graph
       ├─ detect baseline communities
       ├─ validate graph artifact
       └─ R2/MinIO: immutable graph.json.gz + active manifest

QUERY RUN
query
 └─ embed query
    └─ Qdrant retrieval
       └─ document IDs + chunk UIDs
          └─ load each document graph artifact
             └─ temporary namespaced subgraph/view
                └─ community ranking + bounded context allocation
                   └─ existing prompts/map/reduce/evaluation
```

## Storage and lifecycle contract

```text
Qdrant:
  vectors, chunk text, document_id, chunk_uid, hierarchy/layout payload
  optional cached graph_version

R2/MinIO:
  images/{document_id}/...
  graphs/{collection}/{document_id}/v{version}/graph.json.gz
  graphs/{collection}/manifest.json
```

The graph artifact stores references, not duplicated full chunk text:

```text
manifest
nodes
edges
communities
raw_evidence
```

Lifecycle:

1. Parse and embed the full document.
2. Write vectors to Qdrant.
3. Build the graph from the same in-memory chunks/embeddings.
4. Upload and validate an immutable graph version.
5. Update the object-storage active manifest last.
6. If graph construction fails, keep vectors usable and record `partial`/`unavailable` status.
7. `append` affects only the new document; `replace-document` creates a new graph version; `replace-collection` rebuilds the collection.
8. Backfill existing points without re-embedding. Legacy points without `document_id` require rebuild/re-ingest; never guess document ownership.

## Implementation PR sequence

### Phase 0 — land the decisions (COMPLETE)

Merge the ADR stack in order so the implementation branch starts from `main` with the accepted contracts. The current PR bases are stacked, so retarget the next PR to `main` after its predecessor lands:

```text
1. PR #62 → main
2. Retarget PR #63 base to main, then merge PR #63 → main
3. Retarget PR #64 base to main, then merge PR #64 → main
4. Retarget PR #65 base to main, then merge PR #65 → main
```

PR #66 is independent and already targets `main`; merge it after the ADR stack so the handoff lands alongside the accepted decisions. After each merge, fetch the updated `main` before creating the next branch. Do not implement runtime code on the docs/ADR branches.

The resulting landing order is:

```text
main
 ├─ #62 ADR persistent graph
 ├─ #63 ADR relation recovery
 ├─ #64 ADR topology/community
 ├─ #65 ADR context allocation
 └─ #66 implementation handoff
```

### PR A — persistent ingest graph foundation

**Branch:** `feat/ingest-graph-foundation` from updated `main`  
**Target:** `main`  
**Issues:** close #39 and #69.

#69 is the persistent graph artifact/backfill delivery issue because Wayfinder #58 is a resolved decision ticket, not a code-delivery issue. Issues #45 and #46 are delivered with PR B under ADR 0002's ownership split.

#### What to do

1. Preserve the existing launcher and document-safe Qdrant identity contract.
2. Build graph input from every chunk in the ingested document, not from a query result.
3. Add hybrid entity/relation availability reporting and preserve structured raw relation evidence separately from the active graph.
4. Keep optional LLM extraction on the existing provider fallback chain; no provider must be mandatory for ingest.
5. Build the active graph with the current fixed topology/Leiden baseline. Adaptive topology is intentionally deferred to PR C.
6. Persist the versioned `graph.json.gz` artifact and update the active manifest only after validation.
7. Add graph status and independent backfill/rebuild behavior.
8. Keep image export/storage unchanged except for documenting the separate `images/` prefix.

#### Desired outputs

- A successful Ingest Run leaves vectors in Qdrant and a reusable graph artifact in R2/MinIO.
- Artifact counts and status are inspectable: chunks, nodes, edges, communities, raw/active evidence, version, and failure reason.
- `append`, `replace-document`, and `replace-collection` do not corrupt active graph pointers.
- Existing collections can be backfilled without re-embedding when `document_id` exists.
- Query runs can load the artifact and use a temporary graph view; missing artifacts use the compatibility fallback.
- Tests cover happy path, partial/unavailable graph build, replacement, backfill, legacy rejection, and artifact/manifest validation.

### PR B — bounded global relation recovery

**Branch:** `feat/global-relation-recovery` from merged PR A  
**Target:** `main`  
**Issues:** close #45, #46, #47, and #48. #39 remains the extraction reliability foundation from PR A.

#### What to do

- Define the backward-compatible local relation-evidence contract, including confidence, scope, evidence type, support chunk IDs, verification state, and resolved weak-edge weights.
- Canonicalize conservative entity surface variants, preserve aliases/confidence, and report deterministic weak/orphan/query-protected support classifications.
- Start recovery from weak/orphan regions within one document.
- Generate candidates only from bounded semantic-neighbor and hierarchy/section neighborhoods.
- Enforce stable per-region and per-document candidate caps.
- Verify using bounded evidence windows, not the whole document.
- Try the configured LLM providers sequentially through the shared fallback chain; keep candidates unverified if all fail.
- Store direct entity-to-entity edges with relation, source, confidence, status, and supporting chunk IDs.
- Keep weak/rejected/unverified evidence in diagnostics; only explicit/verified relations enter the active graph.
- Exclude unsupported orphan entity nodes from active topology without deleting their diagnostic evidence.

#### Desired outputs

- Candidate, verification, recovery, and rejection artifacts.
- Stable counts for local, cross-chunk, accepted, rejected, and unverified relations.
- No unbounded all-pairs search or mandatory LLM dependency.
- Existing query-protected chunks remain eligible even when their entity graph is weak.

### PR C — adaptive topology and stable community selection

**Branch:** `feat/adaptive-topology-community` from merged PR B  
**Target:** `main`  
**Issues:** close #49, #50, and #51.

#### What to do

- Make adaptive mutual-kNN the per-document default.
- Derive similarity cutoffs from the document distribution and enforce graph-shape guardrails.
- Preserve the fixed policy as a fallback/baseline.
- Explore bounded Leiden resolutions and deterministic seeds; do not target a fixed number of communities.
- Reject/penalize fragmentation, excessive singleton/noise, empty, or severely imbalanced candidates.
- Normalize modularity, semantic coherence, stability, and size balance under a named selection policy.
- Measure seed stability with ARI/NMI; persist candidate metrics and rejection reasons.
- Run agglomerative embedding clustering as diagnostic-only comparison. Do not add HDBSCAN unless later evidence justifies it.
- Persist the selected partition at ingest; do not rerun Leiden for every query.

#### Desired outputs

- Resolved topology policy and thresholds.
- Candidate partition metrics, stability, tie-break, and selected partition.
- Embedding-cluster comparison artifact showing agreement/disagreement.
- A deterministic active community partition reusable by later queries.

### PR D — query-time adaptive context allocation

**Branch:** `feat/adaptive-context-allocation` from merged PR C  
**Target:** `main`  
**Issues:** close #40 and #52.

#### What to do

- Replace fixed `top_k_per_community` and `top_k_global` with a total evidence character budget.
- Score community importance using query similarity, retrieval mass, graph/relation support, unique evidence, and section diversity.
- Reserve minimum coverage for relevant communities, distribute remaining budget by normalized importance, and cap each community.
- Select chunks by relevance, graph/relation/path support, and marginal novelty; stop when new evidence is redundant.
- Preserve query-protected chunks.
- Consume #40 path signal when available; renormalize signals and continue when unavailable.
- For multi-document queries, load namespaced graph views temporarily without persistent cross-document edges.
- Fall back from persistent graph to query-time compatibility graph, then vector-only summarization.

#### Desired outputs

- Explainable community/chunk allocation decisions.
- Selected and rejected evidence reasons.
- Character budget, consumed budget, path status, fallback status, and novelty/marginal-gain diagnostics.
- Existing NAP/CAP/CGM prompts, reduction, evaluation, and feedback behavior remain intact.

## Testing and verification contract

Prefer the highest existing seam:

- `tests/test_flowchart_alignment.py` for graph → community → context handoffs.
- `tests/test_ingest_runner.py` for ingest lifecycle and failure behavior.
- `tests/test_qdrant_handler_cloud.py` for payload, batch, manifest/pointer, and legacy behavior.
- Focused deterministic graph tests for relation evidence, candidate budgets, topology, Leiden candidates, ARI/NMI stability, and context allocation.

Every implementation PR should run:

```bash
uv run pytest -q
uv run python -m py_compile <changed-python-files>
git diff --check
```

Live Qdrant/R2/LLM smoke tests are optional and must not be required for deterministic CI. Use fake providers, fake embeddings, and synthetic graph fixtures for candidate and partition behavior.

## Issue and merge policy

- PR A–D target `main` sequentially. Create each branch from the latest merged `main`; do not merge implementation PRs into the ADR/doc branches.
- The implementation landing order is `PR A → main`, then `PR B → main`, then `PR C → main`, then `PR D → main`. Each later branch is created only after the previous PR is merged and the tests are green.
- Use explicit closing keywords in implementation PR bodies only, for example `Closes #47` and `Closes #48`.
- Issues close automatically only when the PR is merged into the repository default branch. References in an intermediate stacked PR do not replace final verification.
- ADR PRs #62–#65 do not close implementation issues.
- Wayfinder #57 and #58–#61 are already closed as planning decisions; they are not code-completion issues.
- Keep #44 open while its implementation children remain open. After #45–#52 and the new persistent-graph issue are delivered and verified, close #44 manually with a final before/after summary.
- Do not include #35, #36, #41, #42, or #43 in this route; they remain separate follow-ups.

## Stop condition

The route is implementation-complete only when:

1. ADR PRs are landed in `main`.
2. PR A–D are merged in order with fresh tests passing.
3. Graph artifacts exist for newly ingested documents and backfilled collections.
4. Query runs reuse graph artifacts and preserve safe fallbacks.
5. All selected/rejected adaptive decisions are observable in artifacts.
6. Child issues are closed with evidence, then parent #44 is manually closed.

## Suggested skills

- `/implement` — execute one implementation PR from its approved issue contract.
- `/test-driven-development` — add focused regression tests before changing behavior.
- `/code-review` — review each PR for scope, correctness, and missing acceptance criteria.
- `/requesting-code-review` — request review before merge.
- `/verification-before-completion` — verify tests, artifacts, issue closures, and merge state.
- `/github:github` — inspect and manage issue/PR relationships.
- `/finishing-a-development-branch` — prepare each implementation branch for merge.
