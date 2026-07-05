# PRD — profile-driven single launcher for graph-rag-summarizer

Date: 2026-07-05
Status: Published as issue #13; implemented as of 2026-07-05

## Problem Statement

The repository currently makes human operators think in implementation-shaped commands and environment variables instead of in the actual runtime choices they care about.

Today:

- `main.py` always executes the Full-Pipeline Run,
- `upload_to_qdrant.py` is a separate entrypoint for ingestion,
- runtime choices such as query text, retrieval limit, backend mode, and PDF path are pushed into environment variables,
- and `.env` mixes credentials, infrastructure defaults, and per-run inputs.

From a user perspective, this creates avoidable friction:

- there is no single obvious way to run the project,
- a user who only wants a Query-Only Run is forced through a Full-Pipeline-shaped entrypoint,
- runtime choices that should be asked per run are buried in configuration,
- local versus cloud execution is exposed as low-level selectors instead of a coherent Launch Profile,
- and missing credentials or incomplete configuration are discovered too late.

The result is a launcher UX that is harder to learn, harder to automate cleanly, and easier to misconfigure than it needs to be.

## Solution

Turn `main.py` into the single human-facing launcher for the project, with three Launcher Modes:

1. Ingest Run
2. Query-Only Run
3. Full-Pipeline Run

The launcher should work in both interactive and non-interactive use:

- **CLI flags** take highest priority,
- if required runtime inputs are still missing and the session is interactive, the launcher opens a lightweight wizard,
- if the session is non-interactive and required runtime inputs are missing, the launcher fails fast with a clear message,
- and `.env` remains the home for credentials and Stable Defaults rather than per-run operational answers.

The launcher should present runtime decisions in domain terms:

- Launch Profile: `local`, `cloud`, or configured default
- Collection Target
- query text
- retrieval limit
- PDF source path when relevant

The launcher should also keep older entrypoints working for backward compatibility, especially the existing ingest script.

## Implementation status note (2026-07-05)

Current code **implements this PRD**.

Delivered in the launcher:

- interactive Launch Profile selection with a configured default
- per-run local/cloud session overrides without rewriting `.env`
- Query-Only, Ingest, and Full-Pipeline modes through the same human-facing entrypoint
- repo-local PDF discovery / scan for ingest, plus manual PDF-path fallback
- existing-collection risk messaging and explicit confirmation for ingest
- summary-screen edit loop instead of exit-on-cancel
- a thin backward-compatible `upload_to_qdrant.py` wrapper over the shared ingest runner

Issue `#12` remains separate by design and is not part of this launcher PRD.

## User Stories

1. As a local operator, I want one obvious launcher entrypoint, so that I do not have to remember separate scripts for everyday usage.
2. As a cloud operator, I want the same launcher to work against cloud infrastructure, so that local and cloud operation feel consistent.
3. As a user, I want to choose an Ingest Run, so that I can add a PDF to Qdrant from the main launcher.
4. As a user, I want to choose a Query-Only Run, so that I can inspect retrieved chunks without paying the cost of the full summarization pipeline.
5. As a user, I want to choose a Full-Pipeline Run, so that I can go from retrieval to final summary from the same launcher.
6. As a user, I want Launch Profiles described as `local` and `cloud`, so that I can think in operational environments instead of low-level backend flags.
7. As a user, I want the configured default Launch Profile shown to me, so that I can accept it quickly when it is correct.
8. As a user, I want per-run profile choices to apply only to the current run, so that I do not accidentally rewrite shared repository configuration.
9. As a user, I want `.env` to hold credentials and Stable Defaults, so that operational prompts stay short and secrets stay in one place.
10. As a user, I want runtime values such as query text and retrieval limit asked at run time, so that I do not keep editing `.env` for one-off runs.
11. As a user, I want Query-Only Runs to work without Groq credentials, so that retrieval remains available even when summarization is not configured.
12. As a user, I want the launcher to validate whether a mode is available before I start it, so that I do not wait through a long run only to fail on missing configuration.
13. As a user, I want unavailable modes or profiles to explain which configuration is missing, so that I know what to fix.
14. As a user, I want the launcher to fetch available Collection Targets when possible, so that I can choose from real data instead of guessing names.
15. As a user, I want a manual Collection Target fallback if collection discovery fails, so that a temporary connection problem does not completely block me.
16. As a user, I want Query-Only Runs to print concise chunk results in the terminal, so that I can inspect retrieval quality quickly.
17. As a user, I want Query-Only Runs to also save machine-readable output, so that I can reuse results for debugging or later analysis.
18. As a user, I want query text to be required for query-shaped modes, so that every run is intentional.
19. As a user, I want retrieval limit to default sensibly but remain overridable, so that I can tune breadth without editing configuration.
20. As a user, I want optional local PDF-path input during query-shaped modes, so that page-image enrichment remains available when I actually have the source file locally.
21. As a user, I want the Ingest Run to help me pick a local PDF, so that common local usage is faster than manually typing every path.
22. As a user, I want manual PDF-path entry to remain available, so that I am not locked into repository-local files.
23. As a user, I want the launcher to suggest a safe Collection Target for ingestion from the PDF name, so that the default path reduces overwrite risk.
24. As a user, I want existing collections shown with clear risk messaging during ingestion, so that I understand when I am choosing a potentially unsafe path.
25. As a user, I want ingestion into an existing collection to require explicit confirmation, so that I do not accidentally overwrite data.
26. As an operator, I want the launcher to show a final summary screen before execution, so that I can catch wrong profile, collection, query, or file choices.
27. As an operator, I want cancellation from the summary screen to return me to editing instead of exiting entirely, so that I do not have to restart the whole flow.
28. As a maintainer, I want the launcher to remain automatable, so that scripts and CI can drive it without interactive prompts.
29. As a maintainer, I want non-interactive runs with missing inputs to fail fast, so that automation never hangs waiting for input.
30. As a maintainer, I want legacy runtime env values and older entrypoints to keep working, so that the new launcher does not break existing habits abruptly.
31. As a maintainer, I want Query-Only Runs to lazy-load only the modules they need, so that retrieval stays lightweight and tolerant of missing full-pipeline dependencies.
32. As a maintainer, I want Launch Profile resolution to stay backward-compatible with the current backend selectors, so that the project can evolve without a disruptive env migration.
33. As a maintainer, I want minimal `.env` contract cleanup around stale MinIO naming, so that configuration becomes less error-prone without a hard break.
34. As a tester, I want the launcher contract covered by targeted tests at the entrypoint seam, so that mode routing and validation regressions fail fast.
35. As a collaborator, I want the README to teach the launcher workflow instead of a collection of scripts plus env tricks, so that new users can operate the repo without chat history.

## Implementation Decisions

- `main.py` becomes the single human-facing launcher while the existing ingest script remains as a thin backward-compatible wrapper.
- The launcher exposes exactly three Launcher Modes in the first pass: Ingest Run, Query-Only Run, and Full-Pipeline Run.
- The runtime-precedence contract is fixed as **CLI flags > interactive wizard > Stable Defaults from configuration**.
- Interactive prompting happens only when required runtime inputs are still missing and a TTY is available.
- Non-interactive runs never open the wizard; they fail fast and explain which required inputs are missing.
- Launch Profile is the user-facing concept. The launcher maps `local` to the local Qdrant plus MinIO pairing and `cloud` to the cloud Qdrant plus R2 pairing.
- Launch Profile choices are Session Overrides only; the launcher must not rewrite `.env`.
- `.env` becomes the home for credentials and Stable Defaults, not the preferred interface for per-run values like query text or retrieval limit.
- A new explicit default-profile setting is added for human-facing launcher behavior, while existing backend-selector settings remain supported for backward compatibility.
- Query-Only Run is a true retrieval-only path. It must not require Groq credentials and should avoid loading unnecessary full-pipeline dependencies.
- Full-Pipeline Run continues to use the existing summarization path and therefore requires Groq availability, but storage remains optional unless the user also opts into local PDF-based page-image enrichment.
- Ingest Run defaults toward safety by suggesting a Collection Target derived from the PDF name and requiring explicit confirmation before targeting an existing collection.
- Collection discovery should use existing Qdrant integration when possible, but manual Collection Target entry remains a supported fallback.
- Availability checks validate configuration completeness, not live remote health, in the first pass.
- `PDF_PATH`, `QUERY_TEXT`, and `RETRIEVAL_LIMIT` remain backward-compatible inputs, but the launcher and docs stop treating them as the primary human workflow.
- Minimal configuration cleanup should reconcile stale MinIO naming while keeping compatibility for older environment keys where practical.
- The preferred testing seam is the launcher contract itself: mode resolution, input precedence, availability gating, and mode-specific execution behavior.

## Testing Decisions

- Good tests should verify user-observable launcher behavior rather than internal helper structure.
- The highest-value seam is the main launcher contract: given flags, config, and TTY state, the correct mode, validation, and execution path should follow.
- Add focused tests for mode resolution, precedence rules, non-interactive fail-fast behavior, profile availability messaging, and confirmation-loop behavior.
- Add Query-Only Run contract tests that prove retrieval output is produced without Groq-dependent pipeline requirements.
- Add ingest-flow tests for suggested Collection Target naming, existing-collection guardrails, and PDF-path validation.
- Add Full-Pipeline Run routing tests that prove the launcher gates availability correctly before dispatching into the existing pipeline.
- Add backward-compatibility tests around legacy env inputs and older ingestion entrypoint behavior.
- Use the current entrypoint and Qdrant-handler tests as prior art for test style and seam selection.

## Out of Scope

- Reworking the summarization, graph, or evaluation algorithms themselves.
- Solving the future multi-document-safe shared-collection ingest problem that already lives in issue `#12`.
- Adding a GUI, TUI framework, or external dependency for prompts.
- Implementing live connectivity probes for every backend at menu time.
- Moving advanced embedding and image-export settings into the interactive wizard.
- Introducing multiple new top-level launcher scripts for each mode.

## Further Notes

- The launcher should optimize for human clarity first and still preserve scriptability.
- The first pass should keep the code boring: standard library prompts, standard library argument parsing, and the smallest possible compatibility layer.
- The most important product distinction is that Query-Only Run becomes a real first-class path rather than a partial use of the Full-Pipeline Run.
