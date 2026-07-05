# Completed Tasks

## 2026-07-05

- **Implemented and review-aligned multi-provider LLM fallback for summarization (issues #18, #19; draft PR #20)**
  - Created `summarizer/provider_router.py` with ProviderRouter support for Groq, Gemini, NVIDIA NIM, and OpenRouter.
  - Rewrote `summarizer/llm_summarizer.py` and `summarizer/hierarchical_reducer.py` to use a shared provider router session.
  - Wired the real full-pipeline path in `launcher/runners.py` to create one run-scoped provider session and inject that same session into both map summarization and final reduction.
  - Enforced the approved no-fallback contract: when `LLM_ENABLE_FALLBACK=false`, the router now tries only `LLM_PROVIDER` and fails clearly if that provider is unknown or unavailable.
  - Expanded provider availability checks so missing required configuration is not limited to API keys; model/base URL requirements are now respected where applicable.
  - Passed the global timeout through the Gemini `google-genai` client via `http_options`.
  - Aligned launcher availability gating with the provider-router contract so full-pipeline runs accept any correctly configured provider instead of hard-requiring Groq.
  - Added LLM provider config to `config/settings.py`: `LLM_PROVIDER`, `LLM_FALLBACK_CHAIN`, `LLM_ENABLE_FALLBACK`, `LLM_REQUEST_TIMEOUT_SECONDS`, plus per-provider credentials/models/base URLs.
  - Default fallback chain remains `groq -> gemini -> nvidia -> openrouter`.
  - Empty/whitespace output is treated as a hard failure; auth errors skip retry; transient errors get 2 retries with exponential backoff; sticky failover remains run-scoped.
  - Added `google-genai==2.10.0` and `openai==2.44.0` to dependencies.
  - Updated `env.example` and `README.md` for the multi-provider contract.
  - Added 34 total regression tests for this feature across `tests/test_provider_router.py`, `tests/test_shared_session.py`, `tests/test_full_pipeline_shared_session_wiring.py`, `tests/test_full_pipeline_dispatch.py`, `tests/test_launcher_contract.py`, and `tests/test_embedding_entrypoints.py`.
  - Reopened issues #18 and #19 after review found spec gaps, added corrective issue comments, and opened draft PR #20 to carry the fix branch.
  - Verification: `uv run python -m py_compile launcher/contract.py launcher/runners.py summarizer/provider_router.py summarizer/llm_summarizer.py summarizer/hierarchical_reducer.py tests/test_provider_router.py tests/test_shared_session.py tests/test_full_pipeline_shared_session_wiring.py tests/test_full_pipeline_dispatch.py tests/test_launcher_contract.py tests/test_embedding_entrypoints.py`; `uv run pytest -q` (124 passed).

- **Prepared a fresh implementation handoff for the multi-provider LLM fallback work**
  - Added `docs/handoff-2026-07-05-multi-provider-llm-fallback-implementation.md` for the next implementation agent.
  - Tailored the handoff around parent issue `#17` and execution slices `#18` and `#19`, including current repo state, locked constraints, desired output, verification expectations, and suggested skills.
  - Kept the handoff implementation-focused and referenced the published PRD/issues instead of duplicating them.
  - Verification: reviewed the published issue bodies for `#17`, `#18`, and `#19`; checked the current working tree; saved a temp-dir copy per the handoff skill contract.

- **Published the multi-provider LLM fallback planning set**
  - Added glossary terms for Preferred Provider, Fallback Chain, Shared LLM Session, Sticky Failover, and Hard Failure in `CONTEXT.md`.
  - Wrote `docs/prd-2026-07-05-multi-provider-llm-fallback.md` and published it as GitHub issue `#17`.
  - Broke the PRD into two ready-for-agent execution slices in `docs/slice-2026-07-05-multi-provider-llm-fallback.md` and published them as GitHub issues `#18` and `#19`.
  - Locked the first-pass scope to summarization and final reduction only; relation extraction stays out of scope for this provider router pass.
  - Verification: `gh issue create --title "PRD: multi-provider LLM fallback for summarization runs" ...`; `gh issue create --title "Ship provider-routed map summarization with Groq, Gemini, NVIDIA NIM, and OpenRouter fallback" ...`; `gh issue create --title "Reuse the shared provider session for final reduction" ...`; `gh issue list --state open --limit 50 --json number,title,labels,url`.

- **Ignored local-only workspace clutter in git**
  - Added `.commandcode/` plus the currently untracked personal PDF/image files to `.gitignore`.
  - Confirmed `.venv/` and `.vscode/` were already covered, so no broader ignore changes were needed.
  - Verification: `git check-ignore -v .commandcode 'The Let Them Theory.pdf' 'WhatsApp Image 2026-06-25 at 20.20.50.jpeg' .venv .vscode`; `git status --short --ignored`.

- **Closed the remaining single-launcher PRD gaps**
  - Added repo-local PDF discovery / scan for interactive ingest and kept manual PDF-path entry as the fallback path.
  - Added existing-collection risk messaging plus an explicit confirmation step for ingest; non-interactive ingest now requires `--confirm-existing-collection` to target an existing collection intentionally.
  - Fixed the summary-screen flow so declining execution returns to edit mode instead of exiting.
  - Wired Launch Profile selection into real per-run session overrides for Qdrant and storage backends instead of leaving the profile as summary-only UI state.
  - Converted `upload_to_qdrant.py` into a thin backward-compatible wrapper over the shared ingest runner.
  - Added targeted regression coverage for PDF discovery, ingest confirmation behavior, summary edit looping, and legacy upload-wrapper delegation.
  - Verification: `uv run pytest -q` (90 passed); `uv run python -m py_compile main.py upload_to_qdrant.py launcher/contract.py launcher/runners.py storage/factory.py storage/minio_handler.py storage/r2_handler.py vectordb/qdrant_handler.py tests/test_launcher_contract.py tests/test_launcher_main.py tests/test_upload_to_qdrant_wrapper.py tests/test_embedding_entrypoints.py`.

- **Corrected the launcher planning artifacts after a repo-vs-PRD audit**
  - Re-read the launcher handoff, local PRD, GitHub parent issue `#13`, GitHub ingest slice `#15`, and the current launcher code to separate what is actually shipped from what was prematurely marked complete.
  - Revised `docs/handoff-2026-07-05-profile-driven-single-launcher-implementation.md` so it no longer claims the whole roadmap is done; it now calls out the remaining ingest and summary-loop gaps directly.
  - Added an implementation-status note to `docs/prd-2026-07-05-profile-driven-single-launcher.md` so the PRD remains the same contract but no longer reads like the repo already satisfies every parent requirement.
  - Synced the tracking intent for GitHub issue `#13` and the remaining ingest work in issue `#15` instead of leaving the docs in an over-closed state; issue `#15` is reopened and issue `#13` stays open with an explicit partial-implementation note.
  - Verification: compared the live launcher files against the PRD and slice issues; ran `uv run pytest -q` (81 passed); then confirmed `gh issue view 13 --json state,body` and `gh issue view 15 --json state,body` show the corrected tracker state.

- **Implemented most of the profile-driven single launcher (issue #14 complete, issue #16 complete enough, issue #15 follow-up remaining)**
  - Rewrote `main.py` as the single human-facing launcher with three Launcher Modes: Query-Only Run, Ingest Run, and Full-Pipeline Run.
  - Added `launcher/contract.py` with profile resolution (CLI > LAUNCHER_PROFILE env > legacy backend selectors), mode resolution, availability checks, collection discovery, CLI parsing, interactive wizard, summary confirmation, and non-interactive fail-fast.
  - Added `launcher/runners.py` with mode-specific runners: `run_query_only` (retrieval-only, no Groq dependency), `run_ingest` (PDF validation, collection suggestion), `run_full_pipeline` (dispatches to existing retrieval-graph-summarize-evaluate flow).
  - Query-Only Run is a true first-class path that does not import Groq or full-pipeline modules.
  - `upload_to_qdrant.py` preserved as backward-compatible ingest entrypoint.
  - Added `LAUNCHER_PROFILE` setting to `env.example`.
  - Updated `README.md` to teach the launcher workflow with CLI examples.
  - Added 37 new tests across 4 test files: `test_launcher_contract.py` (31), `test_query_only_runner.py` (3), `test_ingest_runner.py` (4), `test_full_pipeline_dispatch.py` (4).
  - Updated `test_embedding_entrypoints.py` to work with the new launcher architecture.
  - Full test suite passes: 81 tests, 0 failures.
  - Query-Only (`#14`) and Full-Pipeline (`#16`) can stay closed, but the ingest slice (`#15`) still has follow-up work around PDF discovery, ingest-specific risk messaging, and explicit existing-collection confirmation.
  - Commented on GitHub issues #14, #15, and #16 with implementation summaries; follow-up tracker correction is still needed for `#15`.
  - Verification: `uv run python -m pytest tests/ -v` (81 passed); `gh issue view 14,15,16 --json state`.

- **Clarified the current PDF ingest behavior for local/cloud Qdrant flows**
  - Re-checked the live ingest path across `upload_to_qdrant.py`, `preprocessing/docling_loader.py`, `vectordb/qdrant_handler.py`, `config/settings.py`, and `main.py`.
  - Confirmed the same upload entrypoint works for local or cloud Qdrant via environment selectors, but the current point ID strategy is only safe for fresh collections.
  - Identified the current product gap: reusing one collection for multiple PDFs can overwrite prior chunks because each PDF restarts `chunk_id` from zero and Qdrant uses that value as the point ID.
  - Added a backlog note for future explicit ingest modes and document-safe IDs.
  - Verification: inspected the current runtime code paths and matched the collection/upsert behavior against the active settings defaults.

- **Captured the safe PDF ingest improvement as one future PRD issue**
  - Wrote `docs/prd-2026-07-05-safe-pdf-ingest-modes.md` and published it as GitHub issue `#12`.
  - Kept the improvement unsliced for now; the single PRD issue covers append, replace-document, and replace-collection behavior together.
  - Dropped the temporary local slice draft because no child issues will be published yet.
  - Verification: `gh issue create --title "PRD: safe PDF ingest modes for shared Qdrant collections" ...`; `gh issue view 12 --json number,title,state,labels,url`.

- **Published the profile-driven single-launcher planning set**
  - Added `CONTEXT.md` to codify the launcher vocabulary: Launch Profile, Launcher Mode, Stable Default, Session Override, Collection Target, Ingest Run, Query-Only Run, and Full-Pipeline Run.
  - Added ADR `docs/adr/0001-profile-driven-single-launcher.md` to record the profile-driven single-launcher decision and why Session Overrides beat rewriting `.env`.
  - Wrote `docs/prd-2026-07-05-profile-driven-single-launcher.md` and published it as GitHub issue `#13`.
  - Broke the PRD into ready-for-agent vertical slices and published child issues `#14`, `#15`, and `#16`, then synced the local slice doc with the real issue numbers.
  - Verification: `gh issue create --title "PRD: profile-driven single launcher for graph-rag-summarizer" ...`; `gh issue view 13 --json number,title,state,labels,url,comments`; `gh issue create --title "Ship a Query-Only Run through the single launcher" ...`; `gh issue create --title "Extend the single launcher to Ingest Runs with PDF selection and collection safety guards" ...`; `gh issue create --title "Extend the single launcher to Full-Pipeline Runs with availability checks and optional local PDF enrichment" ...`.

- **Prepared a fresh implementation handoff for the launcher roadmap**
  - Added `docs/handoff-2026-07-05-profile-driven-single-launcher-implementation.md` for the next agent.
  - Tailored the handoff for onboarding plus step-by-step implementation of parent issue `#13` through child issues `#14`, `#15`, and `#16`, while explicitly keeping issue `#12` out of scope.
  - Included repo-state warnings, onboarding order, implementation order, desired outputs, verification expectations, and suggested skills without duplicating the full PRD bodies.
  - Verification: reviewed the existing handoff style, re-checked the open issue set, and saved a matching temp-dir copy per the handoff skill contract.

## 2026-07-04

- **Set up Matt Pocock engineering skill config**
  - Added `AGENTS.md` agent-skills guidance for issue tracker, triage labels, and domain docs.
  - Added `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, and `docs/agents/domain.md`.
  - Added baseline progress-tracking docs: `docs/todo-in-progress.md` and this file.
  - Verification: checked the inserted `## Agent skills` block and confirmed the new docs files exist.

- **Prepared the next dual-backend execution plan**
  - Read the handoff plus the saved dual-backend spec/plan artifacts.
  - Re-checked the live code to confirm the repo is still cloud-first and not yet dual-mode.
  - Wrote `.omx/plans/2026-07-04-dual-backend-next-plan.md` as the execution-ready plan artifact.
  - Verification: confirmed the cited files still match the handoff assumptions before drafting the plan.

- **Created the private GitHub repository baseline**
  - Created the private remote `amaldevice/graph-rag-summarizer`.
  - Initialized local git on `main`, ignored `.omx/` runtime state, and pushed the current project baseline.
  - Recorded the next-pass infra default: local mode keeps persisted Docker volumes; cloud mode uses the existing R2 + Qdrant Cloud resources.
  - Verification: `gh repo view amaldevice/graph-rag-summarizer`, `git push -u origin main`.

- **Implemented the dual local/cloud ingest pass on a PR branch**
  - Published the PRD issue `#1` and slice issues `#2`, `#3`, and `#4`.
  - Added explicit `STORAGE_BACKEND` and `QDRANT_BACKEND` selectors plus MinIO settings.
  - Added MinIO support, storage selection, backend-neutral `DoclingLoader` usage, and explicit Qdrant backend mode handling.
  - Updated the local compose stack with MinIO bucket bootstrap and refreshed backend-neutral docs/smoke wording.
  - Verification: bundled Colab run passed `tests/test_r2_handler.py`, `tests/test_qdrant_handler_cloud.py`, `tests/test_storage_factory.py`, `tests/test_minio_handler.py`, `tests/test_docling_loader_storage_contract.py`, and `tests/test_qdrant_handler_backends.py` (16 passed); `docker compose config` could not run in this environment because `docker` is not installed.

- **Validated the local Docker bootstrap after installing Docker/Compose/Colima**
  - Started Colima, resolved the local Docker context, and confirmed `docker compose config` renders the MinIO + Qdrant stack cleanly.
  - Brought the stack up, verified `http://localhost:9000/minio/health/live` and `http://localhost:6333/collections` both returned `200`, and confirmed the `summarizer-images` bucket exists.
  - Brought the stack back down while preserving the named Docker volumes for the next local run.
  - Verification: `colima start`, `docker compose config`, `docker compose up -d`, `docker compose ps -a`, `docker compose logs minio-init --no-color`, `curl` health checks, `docker compose run --rm ... mc ls local/summarizer-images`, `docker compose down`, `docker volume ls`.

- **Refreshed the README into a compact formal-English guide**
  - Replaced the long Indonesian project overview with a shorter English README focused on workflow, backend modes, setup, quick start, outputs, tests, and current scope.
  - Kept the content aligned with the current dual local/cloud backend implementation and the actual entrypoints in the repository.
  - Verification: reviewed `README.md` after the rewrite, checked the Git diff, and confirmed the document no longer contains the earlier Indonesian sections.

- **Explained the current local-vs-cloud RAG/runtime split**
  - Re-checked the active runtime wiring across `config/settings.py`, `.env`, `upload_to_qdrant.py`, `main.py`, `preprocessing/docling_loader.py`, `storage/factory.py`, `vectordb/qdrant_handler.py`, `summarizer/llm_summarizer.py`, and `graph/entity_extractor.py`.
  - Confirmed the repo supports dual storage/vector backends, but embeddings and Docling extraction run locally while summarization still depends on Groq.
  - Noted the current `.env` is mixed: Qdrant points local, backend selectors are omitted so defaults apply, and the MinIO bucket name differs from the compose bootstrap bucket.
  - Verification: inspected the current config/code paths and compared the active `.env` keys with `docker-compose.yml` and the backend selector defaults.

- **Clarified local embedding download behavior and local runtime scope**
  - Re-checked `embedding/embedder.py`, `requirements.txt`, and the current `.env` keys to confirm the embedder instantiates `SentenceTransformer(EMBEDDING_MODEL)` directly on the local machine.
  - Confirmed the app runtime does not call Colab CLI anywhere in executable code; Colab references only appear in historical planning/verification docs.
  - Verification: searched the repo for `SentenceTransformer`, `EMBEDDING_MODEL`, and `colab`, then compared the hits against the current runtime entrypoints.

- **Assessed ONNX/OpenVINO viability for the local Apple embedding path**
  - Verified the repo pins `sentence-transformers==3.0.1` and that this version's `SentenceTransformer` constructor does not expose the newer backend-switch API for ONNX/OpenVINO.
  - Re-checked the current embedder wiring, then compared it against the current Sentence Transformers, ONNX Runtime CoreML, PyTorch MPS, OpenVINO, and Apple MacBook Neo documentation to judge the best local accelerator path.
  - Conclusion: the shortest good path for this repo on Apple hardware is still PyTorch + MPS; ONNX/CoreML is possible but requires more runtime work, while OpenVINO is a poor fit for Apple A18 Pro acceleration.
  - Verification: inspected the downloaded `sentence-transformers==3.0.1` wheel, reviewed `embedding/embedder.py`, and checked the official docs/source pages cited in the response.

- **Initialized the repository as a uv-managed Python project**
  - Added `pyproject.toml`, `.python-version`, and `uv.lock` for a reproducible Python 3.12 setup under the `graph-rag-summarizer` project name.
  - Imported the existing runtime dependency pins from `requirements.txt`, added `pytest` as a dev dependency, and synced the local `.venv` with the Homebrew Python 3.12 interpreter.
  - Updated `README.md` so collaborators use `uv sync --frozen` and `uv run ...` instead of a manual `pip install -r requirements.txt` flow.
  - Verification: `uv sync --frozen --python /opt/homebrew/bin/python3.12`; `uv run --python /opt/homebrew/bin/python3.12 python - <<'PY' ... import docling, pytest, qdrant_client, sentence_transformers ... PY`; `uv run --python /opt/homebrew/bin/python3.12 python scripts/run_targeted_pytest.py tests/test_r2_handler.py tests/test_storage_factory.py tests/test_minio_handler.py tests/test_qdrant_handler_backends.py -v` (13 passed).

- **Prepared the cross-platform local embedding runtime planning artifacts**
  - Ran a grilling pass to lock the runtime contract for macOS, Windows, Linux, optional ONNX, project-local embedding cache behavior, and same-model ingest/query guarantees.
  - Added `docs/prd-2026-07-04-cross-platform-local-embedding-runtime.md`, `docs/superpowers/plans/2026-07-04-cross-platform-local-embedding-runtime.md`, and `docs/slice-2026-07-04-cross-platform-local-embedding-runtime.md`.
  - Published the parent PRD issue `#6` plus the ready-for-agent slice issues `#7`, `#8`, `#9`, and `#10`.
  - Verification: `gh issue list --state open --limit 20 --json number,title,state,labels`; `gh issue view 6 --json number,title,body,labels`; `gh issue view 7 --json number,title,body,labels`; `gh issue view 8 --json number,title,body`; `gh issue view 9 --json number,title,body`; `gh issue view 10 --json number,title,body`.

- **Implemented the cross-platform local embedding runtime**
  - Added `embedding/runtime_resolver.py` and `embedding/cache_paths.py` to centralize backend/device resolution, platform detection, cache layout, and ONNX dependency probing.
  - Updated `embedding/embedder.py` so ingest and query share the same runtime contract, log requested vs resolved runtime decisions, use repo-root caches, narrow remote-code trust through an explicit allowlist, and fall back to standard Sentence Transformers only for expected ONNX initialization failures.
  - Added explicit embedding runtime settings in `config/settings.py` and `env.example`, including backend, device, local-files mode, trust-remote-code handling, a trust allowlist, and an ONNX allowlist.
  - Upgraded the repository to `sentence-transformers==5.1.2`, added `einops==0.8.2`, and introduced an optional `onnx` dependency group in `pyproject.toml`.
  - Refreshed `README.md` with the cross-platform embedding matrix, ONNX usage notes, cache rules, and `uv`-based setup commands.
  - Added targeted regression coverage for resolver behavior, cache paths, entrypoint wiring, ONNX fallback handling, and embedder runtime arguments.
  - Verification:
    - `uv lock`
    - `uv sync --frozen`
    - `uv sync --frozen --group onnx`
    - `uv run python scripts/run_targeted_pytest.py -v` (39 passed)
    - `EMBEDDING_BACKEND=sentence-transformers EMBEDDING_DEVICE=auto EMBEDDING_TRUST_REMOTE_CODE=True uv run python - <<'PY' ... TextEmbedder().embed_text(...) ... PY` (live macOS MPS smoke with the default Nomic model)
    - `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 EMBEDDING_ONNX_ALLOWED_MODELS=sentence-transformers/all-MiniLM-L6-v2 EMBEDDING_BACKEND=onnx EMBEDDING_DEVICE=auto EMBEDDING_TRUST_REMOTE_CODE=False uv run python - <<'PY' ... TextEmbedder().embed_text(...) ... PY` (live ONNX CPU smoke with a supported model)

- **Merged the cross-platform embedding runtime PR into `main`**
  - Re-checked PR `#11` before merge and confirmed it was open, non-draft, `MERGEABLE`, `CLEAN`, and backed by the already-pushed lore-format feature commit.
  - Rebase-merged `feat/cross-platform-embedding-runtime` into `main`, which preserved the existing implementation commit instead of creating a new merge commit.
  - Confirmed PR `#11` is now merged and issues `#6`, `#7`, `#8`, `#9`, and `#10` are closed.
  - Pruned the stale local remote-tracking ref after GitHub deleted the feature branch.
  - Left `The Let Them Theory.pdf` untracked and untouched.
  - Verification: `gh pr view 11 --json number,state,mergedAt,mergeCommit,url`; `gh issue view 6 --json number,state`; `gh issue view 7 --json number,state`; `gh issue view 8 --json number,state`; `gh issue view 9 --json number,state`; `gh issue view 10 --json number,state`; `git fetch --prune origin`; `git status --short --branch`.
