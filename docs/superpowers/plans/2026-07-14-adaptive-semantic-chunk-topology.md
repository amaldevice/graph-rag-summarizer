# Adaptive Semantic Chunk Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an adaptive mutual-kNN semantic chunk topology with data-dependent similarity cutoffs and degree bounds (min/max degree) as the default policy, while keeping the current fixed kNN policy available as a baseline and fallback.

**Architecture:** Extend `GraphBuilder` in `graph/graph_builder.py` to support both `fixed` and `adaptive` policies. Store resolved topology metrics as metadata in `G.graph["topology_metadata"]`, and modify `GraphAnalyzer` in `graph/graph_analyzer.py` to export this metadata to the run's `graph_summary.json` artifact. Add configuration keys in `config/settings.py` to provide stable defaults without user prompts.

**Tech Stack:** Python 3.12, networkx, scikit-learn, numpy, pytest

---

## File Structure

### Create

- `tests/test_adaptive_topology.py` — unit tests for the adaptive topology policy, degree bounds, determinism, and fallback behavior using synthetic sparse, dense, and degenerate fixtures.

### Modify

- `config/settings.py` — add configuration defaults for graph topology policy, kNN k, similarity threshold, min degree, and max degree.
- `env.example` — document the new environment variables for graph topology.
- `graph/graph_builder.py` — implement the mutual-kNN logic, data-dependent cutoff calculation, degree bounding, stable node ordering, and metadata recording.
- `graph/graph_analyzer.py` — update `save_summary_json` to include the topology metadata from `G` if available.
- `launcher/runners.py` — update `save_summary_json` invocation to pass the graph object `G`.

### Keep unchanged in this plan

- `vectordb/*`
- `storage/*`
- `preprocessing/*`
- `summarizer/*`
- `evaluation/*`
- `pipeline/*`

---

### Task 1: Add configuration keys for the graph topology policy

**Files:**
- Modify: `config/settings.py`
- Modify: `env.example`

- [x] **Step 1: Add the following configuration variables to `config/settings.py`:**
  - `GRAPH_TOPOLOGY_POLICY`: defaults to `"adaptive"` (options: `"fixed"`, `"adaptive"`)
  - `GRAPH_KNN_K`: defaults to `3`
  - `GRAPH_SIM_THRESHOLD`: defaults to `0.3`
  - `GRAPH_MIN_DEGREE`: defaults to `1`
  - `GRAPH_MAX_DEGREE`: defaults to `5`

- [x] **Step 2: Document these new environment variables in `env.example`.**

- [x] **Step 3: Verify compilation:**
  Run: `uv run python -m py_compile config/settings.py`
  Expected: PASS

---

### Task 2: Implement the adaptive topology logic in GraphBuilder

**Files:**
- Modify: `graph/graph_builder.py`

- [x] **Step 1: Modify `GraphBuilder.__init__` to load settings defaults while preserving backward-compatible signature.**
- [x] **Step 2: Implement `_build_semantic_edges` and `_apply_fixed_policy` helpers.**
- [x] **Step 3: Implement data-dependent similarity cutoff derivation (`mean + 0.5 * std_dev` of active similarities).**
- [x] **Step 4: Implement mutual-kNN candidate generation.**
- [x] **Step 5: Implement min/max degree bounding per node using stable graph-node ordering.**
- [x] **Step 6: Store metadata in `G.graph["topology_metadata"]`.**

- [x] **Step 7: Verify compiling:**
  Run: `uv run python -m py_compile graph/graph_builder.py`
  Expected: PASS

---

### Task 3: Export topology metadata in GraphAnalyzer and update runner invocation

**Files:**
- Modify: `graph/graph_analyzer.py`
- Modify: `launcher/runners.py`

- [x] **Step 1: Modify `GraphAnalyzer.save_summary_json` to accept an optional `graph=None` parameter.**
- [x] **Step 2: If `graph` is provided and has `topology_metadata` in its `.graph` attribute, include it in the exported JSON under the key `"topology_metadata"`.**
- [x] **Step 3: Update `launcher/runners.py` to pass `G` when calling `analyzer.save_summary_json(ranked, communities, modularity, ..., graph=G)`.**

- [x] **Step 4: Verify compiling:**
  Run: `uv run python -m py_compile graph/graph_analyzer.py launcher/runners.py`
  Expected: PASS

---

### Task 4: Write tests for adaptive topology and verify correctness

**Files:**
- Create: `tests/test_adaptive_topology.py`

- [x] **Step 1: Write tests covering:**
  - Compatibility check: ensuring the `fixed` policy builds identical graphs to the previous implementation.
  - Mutual kNN extraction.
  - Cutoff calculation on normal similarity distribution.
  - Enforced degree bounds: verifying node degrees do not violate `min_degree` and `max_degree` boundaries.
  - Fallback logic: testing when the active chunk count is < 2 (which should fall back to fixed policy or skip).
  - Determinism: proving that sorting of inputs and nodes yields identical graphs on repeated runs.
  - Degenerate inputs: handling when all similarities are identical or zero.

- [x] **Step 2: Run the new tests:**
  Run: `uv run pytest tests/test_adaptive_topology.py -v`
  Expected: PASS

- [x] **Step 3: Run the entire test suite to ensure no regressions:**
  Run: `uv run pytest`
  Expected: 172+ PASS, 0 failures

---

## Risks and mitigations

- **Risk: Adaptive topology yields too sparse or disjoint graphs, fragmenting communities.**
  - Mitigation: Enforcing `min_degree` (default to 1) guarantees every chunk node connects to at least its closest neighbor, avoiding isolated singletons unless similarity is below baseline `sim_threshold`.
  
- **Risk: Uncontrolled dense connectivity in large documents.**
  - Mitigation: Enforcing `max_degree` (default to 5) caps the semantic degree, avoiding excessive density and keeping downstream Leiden community discovery fast.

- **Risk: Nondeterministic ordering of nodes during degree bounding.**
  - Mitigation: Explicitly sort active node indices and sorting keys by index and weight during edge modifications.

---

## Stop condition

Stop when:
- Adaptive topology with mutual-knn and degree bounds is the default policy.
- Configuration defaults exist in `config/settings.py`.
- Metadata is recorded and exported to `graph_summary.json` artifacts.
- New deterministic unit tests in `tests/test_adaptive_topology.py` pass cleanly.
- The entire pytest suite runs and passes with no regressions.
