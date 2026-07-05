# PRD: artifact-directory Full-Pipeline Runs and stage-aware launcher logging

Published as GitHub issue `#22`.

## Problem Statement

The current launcher asks Full-Pipeline Run users for a `JSON output path`, but the run does not actually honor that input. Full-Pipeline Runs emit many artifacts with hardcoded default filenames under `output/`, so the prompt is misleading and operators cannot direct one run into its own artifact folder.

The launcher output is also too opaque during longer runs. Users can see the run start and eventually finish, but they do not get a reliable stage indicator that tells them where the run currently is, nor do they get an optional higher-detail view when they want more operational clarity.

From the operator perspective, this creates two avoidable problems:

- Full-Pipeline Run output organization is misleading and easy to overwrite.
- Launcher progress is not explicit enough when a run takes time or appears stalled.

## Solution

Keep the launcher surface small and mode-aware:

- Query-Only Run keeps its existing `JSON output path` contract.
- Full-Pipeline Run switches to an `Artifact output directory` contract and writes all of its existing artifacts into that directory while preserving the current internal filenames.
- In interactive use, the launcher prompts with mode-specific labels so users are not asked for a JSON file path when the run will actually emit many files.
- Full-Pipeline Runs default to a unique per-run artifact directory so one run does not overwrite another by accident.
- The launcher adds stage-aware progress output for all Launcher Modes.
- A single optional `verbose` toggle applies across Query-Only Run, Ingest Run, and Full-Pipeline Run.
- Non-verbose output still shows the current stage; verbose output adds counts, selected paths, chosen provider/runtime details, and artifact-save confirmations that make long runs easier to follow.

## User Stories

1. As an operator, I want Full-Pipeline Run output grouped into one artifact directory, so that one run’s files stay together.
2. As an operator, I want the launcher to stop asking for a JSON file path during Full-Pipeline Runs, so that the prompt matches what the run actually produces.
3. As an operator, I want Query-Only Run to keep its existing JSON artifact behavior, so that the simpler mode does not change unnecessarily.
4. As an operator, I want a unique default artifact directory for each Full-Pipeline Run, so that repeated runs do not overwrite each other by default.
5. As an operator, I want the existing Full-Pipeline artifact filenames to stay stable inside the chosen directory, so that my habits and downstream references do not break.
6. As an operator, I want to see which stage the launcher is currently running, so that I know whether the run is progressing.
7. As an operator, I want stage progress in Query-Only Run, so that even short retrieval runs have visible structure.
8. As an operator, I want stage progress in Ingest Run, so that I can tell whether the run is loading, embedding, or uploading.
9. As an operator, I want stage progress in Full-Pipeline Run, so that I can tell whether the run is retrieving, building the graph, summarizing, or evaluating.
10. As an operator, I want a single verbose toggle across all Launcher Modes, so that I do not have to learn three separate debugging controls.
11. As an operator, I want normal output to stay compact, so that routine runs are still readable.
12. As an operator, I want verbose output to add counts and saved-path details, so that I can inspect a run without opening code.
13. As an operator, I want verbose output to show where artifact files were written, so that I can find the outputs immediately.
14. As an operator, I want verbose output to show the active runtime/provider state where relevant, so that I can debug configuration-sensitive runs more quickly.
15. As an operator, I want the summary screen to show the mode-appropriate output target before execution, so that I can catch mistakes before a run starts.
16. As a fork user, I want non-interactive Full-Pipeline Runs to accept an explicit artifact directory, so that automation can control where outputs land.
17. As a fork user, I want non-interactive runs to keep working with a sensible default when I omit the output target, so that scripts do not become more fragile than necessary.
18. As a maintainer, I want the launcher contract to reflect the actual output behavior of each mode, so that the CLI and wizard stay honest.
19. As a maintainer, I want the progress output implemented at the launcher seam instead of scattered ad hoc, so that future mode changes touch fewer places.
20. As a maintainer, I want regression tests around output-target resolution and stage logging, so that future launcher UX work does not silently reintroduce misleading prompts.

## Implementation Decisions

- The launcher keeps one human-facing entrypoint and continues to resolve mode-specific behavior through Launcher Mode rather than adding a second command surface.
- Query-Only Run keeps the current `json_output` concept because it produces one JSON artifact and already matches the prompt.
- Full-Pipeline Run gains an artifact-directory concept instead of overloading the JSON-output concept.
- The new Full-Pipeline artifact-directory value applies only to Full-Pipeline Runs in this pass; Ingest Run and Query-Only Run do not adopt a shared output-directory abstraction yet.
- Full-Pipeline Runs preserve the current artifact basenames and only change their parent directory.
- The default Full-Pipeline artifact directory is unique per run instead of a fixed shared folder.
- Interactive prompts must be mode-aware: Query-Only Run asks for `JSON output path`, while Full-Pipeline Run asks for `Artifact output directory`.
- The run summary must also be mode-aware so it shows the real output target before confirmation.
- A single verbose toggle is added at the launcher level and applies to all modes.
- Stage/state output is always visible for all modes, even when verbose is off.
- Verbose mode adds structured high-level details only: stage transitions, counts, selected output paths, provider/runtime details where already available, and retry/evaluation context where relevant.
- Verbose mode does not introduce a separate log file or persistent manifest in this pass; console clarity is sufficient.
- The highest-value testing seam stays at the existing launcher contract and mode-runner seams rather than introducing a new generalized logging framework.

## Testing Decisions

- Good tests should verify observable launcher behavior: prompts, defaults, resolved config, stage markers, and output paths. They should not assert incidental internal helper structure.
- Existing launcher contract tests are the highest seam for checking mode-aware prompt/default behavior and summary rendering.
- Existing mode-runner tests are the highest seam for checking that Query-Only Run, Ingest Run, and Full-Pipeline Run emit the expected stage/state output and honor the resolved output target.
- Add regression coverage for Full-Pipeline default artifact-directory generation, explicit artifact-directory forwarding, and stable artifact basenames under the selected directory.
- Add regression coverage for interactive/non-interactive mode-specific labels so Query-Only Run and Full-Pipeline Run no longer share the wrong output prompt.
- Add regression coverage that non-verbose runs still show the current stage, while verbose runs add the extra structured details for each mode.
- Reuse the existing launcher-oriented test style already present around contract resolution, full-pipeline dispatch, Query-Only Run artifacts, and ingest behavior.

## Out of Scope

- Renaming existing Full-Pipeline artifact files.
- Adding a new artifact directory concept to Query-Only Run.
- Adding a persistent log file, run manifest, or log-export feature.
- Adding multiple verbosity levels beyond a single on/off toggle.
- Changing the summarization/evaluation logic itself.
- Retrying, resumability, or progress bars.
- Revisiting the separate safe multi-PDF ingest work tracked in issue `#12`.

## Further Notes

- This is a launcher honesty and operator-clarity pass, not a pipeline-algorithm rewrite.
- The smallest acceptable result is: the Full-Pipeline output target becomes truthful and every Launcher Mode shows its current stage.
