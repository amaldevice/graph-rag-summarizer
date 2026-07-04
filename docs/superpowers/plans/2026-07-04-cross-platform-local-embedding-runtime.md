# Cross-Platform Local Embedding Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one cross-platform local embedding runtime contract that defaults safely on Windows/Linux, prefers MPS on macOS, keeps ONNX optional, and preserves one embedding-model contract across ingest and query.

**Architecture:** Keep `embedding/embedder.py` as the public entrypoint, but move runtime choice into one shared resolver that reads config, detects host capabilities, chooses the final backend/device, and reports fallbacks. Default execution continues through `sentence-transformers`, while the ONNX path stays optional, lazy-prepared, and isolated behind the same resolver contract.

**Tech Stack:** Python 3.12, uv, sentence-transformers, PyTorch/MPS, optional ONNX runtime, pytest

---

## File Structure

### Create

- `embedding/runtime_resolver.py` — resolve requested backend/device into a single runtime decision.
- `embedding/cache_paths.py` — compute project-local cache paths under `.cache/embedding/`.
- `tests/test_embedding_runtime_resolver.py` — resolver behavior across OS and capability combinations.
- `tests/test_embedding_cache_paths.py` — local cache-path contract tests.
- `tests/test_text_embedder_runtime.py` — public `TextEmbedder` runtime selection and fallback tests.
- `tests/test_embedding_entrypoints.py` — thin ingest/query wiring checks.
- `tests/test_onnx_runtime_contract.py` — optional ONNX allowlist and fallback tests.

### Modify

- `config/settings.py` — add embedding backend/device/cache config and optional ONNX allowlist config.
- `env.example` — document default embedding runtime settings.
- `embedding/embedder.py` — consume the shared resolver, apply project-local caches, and log resolved runtime decisions.
- `upload_to_qdrant.py` — preserve the same `TextEmbedder` contract while exposing runtime logs during ingest.
- `main.py` — preserve the same `TextEmbedder` contract while exposing runtime logs during query.
- `pyproject.toml` — add an optional ONNX dependency group.
- `.gitignore` — ignore project-local `.cache/embedding/` artifacts.
- `README.md` — explain default runtime behavior, optional ONNX usage, cache behavior, and troubleshooting.

### Keep unchanged in this plan

- `vectordb/*`
- `storage/*`
- `preprocessing/*`
- `graph/*`
- `summarizer/*`
- `evaluation/*`
- `pipeline/*`

---

### Task 1: Codify the cross-platform embedding runtime contract

**Files:**
- Create: `embedding/runtime_resolver.py`
- Create: `tests/test_embedding_runtime_resolver.py`
- Modify: `config/settings.py`
- Modify: `env.example`

- [ ] Add explicit embedding config values: backend, device, and ONNX mode flags.
- [ ] Implement one resolver that reads config, detects OS/capabilities, and returns a structured runtime decision.
- [ ] Make macOS prefer `mps` when available and fall back to `cpu`; keep Windows/Linux on `cpu` by default.
- [ ] Add resolver tests for macOS, Windows, Linux, manual overrides, and invalid config.
- [ ] Verify with: `uv run python scripts/run_targeted_pytest.py tests/test_embedding_runtime_resolver.py -v`

### Task 2: Route the default sentence-transformers path through the shared resolver

**Files:**
- Create: `embedding/cache_paths.py`
- Create: `tests/test_embedding_cache_paths.py`
- Create: `tests/test_text_embedder_runtime.py`
- Create: `tests/test_embedding_entrypoints.py`
- Modify: `embedding/embedder.py`
- Modify: `upload_to_qdrant.py`
- Modify: `main.py`
- Modify: `.gitignore`

- [ ] Add project-local cache-path helpers rooted at `.cache/embedding/`.
- [ ] Teach `TextEmbedder` to load the default backend via the resolved device and cache path.
- [ ] Log requested backend/device, detected OS, resolved backend/device, and fallback reasons.
- [ ] Ensure ingest and query both construct `TextEmbedder` through the same contract.
- [ ] Add tests proving the same embedding model setting is used in both entrypoints even when runtime device differs.
- [ ] Verify with: `uv run python scripts/run_targeted_pytest.py tests/test_embedding_cache_paths.py tests/test_text_embedder_runtime.py tests/test_embedding_entrypoints.py -v`

### Task 3: Add the optional ONNX path without destabilizing the default runtime

**Files:**
- Create: `tests/test_onnx_runtime_contract.py`
- Modify: `embedding/runtime_resolver.py`
- Modify: `embedding/embedder.py`
- Modify: `config/settings.py`
- Modify: `pyproject.toml`

- [ ] Add an optional ONNX dependency group in `pyproject.toml` instead of making ONNX part of the default install.
- [ ] Restrict ONNX to a tested allowlist that starts with the repository default embedding model.
- [ ] Add lazy local artifact preparation so ONNX can download/prepare what it needs on first run under `.cache/embedding/onnx/`.
- [ ] If ONNX is requested but unavailable or unsupported, warn clearly and fall back to `sentence_transformers` with the same embedding model whenever possible.
- [ ] Add tests for allowlist enforcement, warning fallback, and same-model fallback behavior.
- [ ] Verify with: `uv run python scripts/run_targeted_pytest.py tests/test_onnx_runtime_contract.py tests/test_text_embedder_runtime.py -v`

### Task 4: Document and lock the operator experience

**Files:**
- Modify: `README.md`
- Modify: `env.example`
- Modify: `tests/test_embedding_runtime_resolver.py`
- Modify: `tests/test_onnx_runtime_contract.py`

- [ ] Document the default runtime matrix for macOS, Windows, and Linux.
- [ ] Document that ONNX is optional/experimental and may fall back with a warning.
- [ ] Document that `.cache/embedding/` is local-only and must not be committed.
- [ ] Add or update tests so the documented config names and fallback behavior remain aligned with the live runtime contract.
- [ ] Verify with: `uv run python scripts/run_targeted_pytest.py tests/test_embedding_runtime_resolver.py tests/test_text_embedder_runtime.py tests/test_onnx_runtime_contract.py tests/test_embedding_entrypoints.py -v`

## Risks and mitigations

- **Risk: silent runtime drift between ingest and query**
  - Mitigation: keep one resolver and one `TextEmbedder` entrypoint; add explicit entrypoint tests.

- **Risk: ONNX adds too much complexity too early**
  - Mitigation: keep it optional, allowlist-based, and behind warning fallbacks.

- **Risk: cross-platform defaults become too magical**
  - Mitigation: log requested and resolved runtime decisions at startup.

- **Risk: large local artifacts leak into Git**
  - Mitigation: keep everything under `.cache/embedding/` and ignore that path explicitly.

## Stop condition

Stop when the repository has:
- one documented embedding runtime contract,
- safe defaults across macOS/Windows/Linux,
- a working macOS MPS default path,
- an optional ONNX contract with fallback behavior,
- project-local embedding caches under `.cache/embedding/`,
- and targeted tests plus docs that match the implemented behavior.
