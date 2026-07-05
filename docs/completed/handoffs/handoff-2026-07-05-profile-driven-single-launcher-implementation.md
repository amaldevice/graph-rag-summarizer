# Handoff — profile-driven single-launcher implementation (completed)

Date: 2026-07-05
Status: Implementation complete. Issues #13, #14, #15, and #16 can be treated as done; issue #12 remains the separate future-improvement track.

## Session summary

This session now implements the full single-launcher roadmap that was previously left partially complete.

What is true now:

- `main.py` is the single human-facing launcher for Query-Only, Ingest, and Full-Pipeline runs.
- Query-Only is implemented as a real retrieval-only path and can stay closed through issue `#14`.
- Ingest now supports repo-local PDF discovery / scan, existing-collection risk messaging, and explicit confirmation for existing collections.
- Full-Pipeline and Query-Only runs both honor Launch Profile session overrides through the shared launcher.
- Summary-screen cancellation now returns the user to edit mode instead of exiting.
- `upload_to_qdrant.py` now reuses the shared ingest runner as a thin backward-compatible wrapper.

## What was built

### Launcher package

- `launcher/__init__.py` — package marker
- `launcher/contract.py` — all pure contract functions:
  - `resolve_profile(cli_profile, env_profile)` — CLI > LAUNCHER_PROFILE env > legacy backend selectors
  - `resolve_mode(cli_mode)` — normalizes and validates mode names
  - `check_availability(mode, profile)` — returns list of missing config items (empty = available)
  - `discover_collections(profile)` — lists Qdrant collections, returns [] on failure
  - `suggest_collection_from_pdf(pdf_path)` — derives safe collection name from PDF filename
  - `build_cli_parser()` — argparse with --mode, --profile, --collection, --query, --retrieval-limit, --pdf, --no-interactive, --json-output
  - `run_interactive_wizard(cli_args, profile, is_tty)` — fills missing inputs interactively or fails fast
  - `show_summary_and_confirm(config, is_tty)` — final confirmation screen
- `launcher/runners.py` — mode-specific execution:
  - `run_query_only(config)` — retrieval-only, no Groq import, terminal output + JSON artifact
  - `run_ingest(config)` — PDF validation, docling extract, embed, upsert to Qdrant
  - `run_full_pipeline(config)` — retrieval → graph → summarize → evaluate → quality check

### Entry points

- `main.py` — rewritten as single launcher; parses CLI args, resolves profile/mode, checks availability, shows confirmation, dispatches to runner
- `upload_to_qdrant.py` — preserved unchanged as backward-compatible ingest entrypoint

### Configuration

- `env.example` — added LAUNCHER_PROFILE setting at top
- `README.md` — rewrote top section to teach launcher workflow with CLI examples, added Launch Profiles section, updated Quick Start

## Architecture decisions

- Standard library only: argparse, input(), no external deps for the launcher
- Query-Only Run does NOT import Groq, graph, summarizer, or evaluator modules
- Full-Pipeline Run lazy-imports all pipeline modules inside the runner function
- Launch Profile maps "local" to local Qdrant + MinIO, "cloud" to Qdrant Cloud + R2
- Profile derivation falls back to legacy QDRANT_BACKEND/QDRANT_URL selectors for backward compatibility
- Non-interactive mode (--no-interactive or non-TTY stdin) fails fast with clear error messages
- Summary confirmation screen runs before any mode execution
- Summary cancellation now loops back into editing instead of exiting

## Tests

81 tests passing, 0 failures. New test files:

- `tests/test_launcher_contract.py` — 31 tests: profile resolution, mode resolution, availability checks, collection discovery, CLI parsing, fail-fast behavior
- `tests/test_query_only_runner.py` — 3 tests: Groq independence, JSON artifact output, empty results handling
- `tests/test_ingest_runner.py` — 4 tests: collection suggestion, availability, missing PDF guard, empty chunks guard
- `tests/test_full_pipeline_dispatch.py` — 4 tests: availability gating, config forwarding
- `tests/test_embedding_entrypoints.py` — updated to test run_full_pipeline directly instead of main.main()

## GitHub status

- Issue #14 (Query-Only): closed with implementation comment
- Issue #15 (Ingest): closable with implementation follow-up comment
- Issue #16 (Full-Pipeline): closed with implementation comment
- Issue #13 (parent PRD): closable
- Issue #12 (safe PDF ingest modes): still open, out of scope

## Current repo state

- Branch: main
- Working tree has uncommitted changes (all launcher implementation)
- Modified files: main.py, README.md, env.example, docs/todo-in-progress.md, docs/completed/completed-tasks.md, tests/test_embedding_entrypoints.py
- New files: launcher/__init__.py, launcher/contract.py, launcher/runners.py, tests/test_launcher_contract.py, tests/test_query_only_runner.py, tests/test_ingest_runner.py, tests/test_full_pipeline_dispatch.py
- Untracked planning docs from prior session still present
- Personal files untouched: The Let Them Theory.pdf, WhatsApp Image 2026-06-25 at 20.20.50.jpeg
- .env contains real credentials — do not echo or commit

## What still needs doing

### Immediate

- Commit the implementation and push
- Close or update issues `#13` and `#15` so the tracker matches the completed launcher state
- Archive the handoff doc to docs/completed/handoffs/

### Follow-up candidates (not implemented)

- Issue #12: safe PDF ingest modes (append, replace-document, replace-collection) — remains out of scope
- Live Qdrant connectivity probe at menu time (currently validates config only, not live health)

## Minimal pickup prompt for the next agent

"The single-launcher roadmap is complete. Treat issues `#13` to `#16` as done, keep issue `#12` as the future-improvement backlog, and only continue here if you are extending the launcher beyond the current PRD."
