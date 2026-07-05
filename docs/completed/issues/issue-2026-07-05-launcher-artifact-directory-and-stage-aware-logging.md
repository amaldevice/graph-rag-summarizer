# Issue draft: ship artifact-directory Full-Pipeline Runs and stage-aware launcher logging

Published as GitHub issue `#23`.

## Parent

- `#22` — `PRD: artifact-directory Full-Pipeline Runs and stage-aware launcher logging`

## What to build

Update the launcher so Full-Pipeline Runs no longer pretend to write one JSON artifact. Instead, they should resolve an Artifact output directory, default that directory uniquely per run, and write the existing Full-Pipeline artifacts into that directory without renaming the files themselves.

At the same time, add stage-aware progress output across all Launcher Modes:

- Query-Only Run
- Ingest Run
- Full-Pipeline Run

The current stage/state should always be visible. A single optional verbose toggle should add clearer structured detail such as counts, resolved output paths, runtime/provider details where relevant, and other high-level operational information, without introducing a separate log-file system.

## Acceptance criteria

- [x] Query-Only Run keeps its JSON artifact contract, but Full-Pipeline Run resolves and displays an Artifact output directory instead of a JSON file path.
- [x] Full-Pipeline Run writes all existing artifacts into the selected artifact directory while preserving the current artifact filenames.
- [x] All Launcher Modes show their current stage during execution, and one shared verbose toggle adds extra structured detail without becoming the default noise level.
- [x] Existing or updated launcher tests cover output-target resolution and stage/verbose behavior at the launcher contract and runner seams.

## Blocked by

None - can start immediately.
