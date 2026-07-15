# Completed Tasks

## 2026-07-15

- **Refreshed onboarding and launcher runbook after PR #81**
  - Documented bounded path scoring/provenance, character-budget allocation,
    embedding-similar reduction with stable-ID fallback, and attempt-scoped
    retry artifacts.
  - Clarified that forced retries are private direct test/dev behavior, not a
    launcher CLI option.
  - Verification: implementation-anchor scan with `rg`; `git diff --check`.

- **Completed Issues #40–#42 implementation in merged PR #81**
  - Added bounded, deterministic PathRAG-style candidate paths with ranked
    selected IDs, rejected-path reasons, per-chunk path evidence, and stable
    insertion-order-independent provenance.
  - Grouped each RAPTOR reduction level by existing embedding similarity and
    recorded the groups, with stable fixed-order fallback for invalid vectors.
  - Added a private direct-run test seam for one forced retrieval, prompt, or
    reduce retry; ordinary launcher input cannot enable it, and attempt reports
    now include the attempt number plus forced-failure provenance.
  - Verification: `./.venv/bin/pytest -q` (**338 passed**); focused path,
    reducer, retry, launcher, and shared-session suites (**93 passed**);
    `./.venv/bin/python -m compileall`; `git diff --check`; independent review
    found and verified the canonical path-frontier fix.
  - Resolved the follow-up review P2: the invalid-embedding fallback now says
    `stable_id_order_fallback`, matching its stable-ID sort, with a regression
    test for both label and grouping order. Re-review clear; final full suite:
    `./.venv/bin/pytest -q` (**339 passed**).

- **Refreshed active documentation for the current project state**
  - Replaced the pre-delivery Flow Project handoff with the current persistent-graph baseline, the five open GitHub issues (#35, #36, #40–#42), and the recommended next slice (#40).
  - Updated starter architecture and runbook guidance for the default-enabled optional persistent graph, selected-evidence evaluation, and compatibility/vector-only fallbacks.
  - Archived the stale 2026-07-13 issue-flow canvas and completed 2026-07-04 plans/specs under `docs/completed/`; repaired their archived references.
  - Synced the live backlog with the current GitHub issue tracker and removed completed #43 from active work.
  - Verification: `gh issue list --state open`; markdown/path reference scan with `rg`; `git diff --check`.

- **Completed Issue #43 lightweight grounded evaluation metrics (PR #78 merged)**
  - Merged PR #78 (`4b784e5`) and GitHub automatically closed Issue #43.
  - Added entity, number/date, sentence-support, citation-coverage, redundancy, query-relevance, and evidence-diversity signals without a new model dependency.
  - Kept quality evaluation bound to explicitly selected pruner evidence; an intentional empty selection no longer falls back to raw retrieval.
  - Added per-sentence chunk-ID traceability, careful date/number normalization, strict unsupported number/date failure, and warning-oriented redundancy/diversity decisions.
  - Added deterministic coverage for available, unavailable, pass, warning, fail, date normalization, discourse markers, selected-evidence behavior, and Full-Pipeline wiring.
  - Resolved the PR review traceability follow-up: citation coverage now retains the strongest stable-ID support even when an ID-less chunk scores higher, preserves `chunk_id=0`, and falls back from empty `chunk_uid` values.
  - Verification: `./.venv/bin/pytest -q` (**332 passed**); focused suite (**34 passed**); `python -m compileall`; `git diff --check`; final two-axis review clear.

## 2026-07-14

- **Completed PR D query-time adaptive context allocation**
  - Merged PR #75 (`44e2e25`) and closed issue #52.
  - Delivered bounded, query-aware community allocation with novelty selection, protected retrieval evidence, prompt-budget safety, inspectable diagnostics, and compatibility-to-vector-only fallback provenance.
  - Verification: `./.venv/bin/pytest -q` (**315 passed**); focused allocation/pipeline suite (**27 passed**); `compileall`; `git diff --check`.

- **Archived completed adaptive-graph delivery artifacts**
  - Moved the completed PRD, issue-slice plan, PR C topology plan, and PR A–D handoff into `docs/completed/`.
  - Kept ADR 0002–0005 as live architecture records and retained issue #40 as the separate PathRAG backlog.
  - Verification: confirmed the merged PRs (#67, #72, #68, #75), closed delivery issues (#39, #45–#52, #69), and `git diff --check`.

- **Completed PR C adaptive topology and stable community selection**
  - Merged PR #68 (`6834ddb`) and closed issues #49–#51.
  - Delivered bounded adaptive topology, deterministic Leiden selection/stability diagnostics, and diagnostic-only agglomerative comparison.
  - Verification: `./.venv/bin/pytest -q` (**306 passed**); targeted 83-test suite; final audit fixes.

- **Completed PR B bounded global relation recovery**
  - Merged PR #72 (`b15507a`) and closed issues #45–#48.
  - Delivered auditable relation evidence, conservative canonical entities, weak/orphan-seeded bounded candidates, validated provider fallback, verified direct cross-chunk edges, and post-recovery noise cleanup.
  - Persisted recovery diagnostics and attempt-scoped compatibility-fallback artifacts.
  - Verification: `./.venv/bin/pytest -q` (**278 passed**); changed-file `py_compile`; `git diff --check`; two-axis code review.

- **Synced the active adaptive-graph PRD with merged PR A delivery**
  - Recorded PR #67 (`1ecc0b4`) as the delivered persistent-ingest foundation and its automatic closure of issues #39 and #69.
  - Kept PR B (#45–#48) as the immediate next implementation slice, with PR C/D explicitly sequenced after it.
  - Verification: cross-checked the merged PR, linked issue status, and the persistent-graph implementation handoff; `git diff --check`.

- **Completed PR A persistent-graph ADR alignment and Issue #39 delivery**
  - Aligned PR #67 with ADR 0002: #39 and #69 are PR A; #45–#48 stay with PR B.
  - Added provider-backed relation availability/mode reporting, including `graph_summary.json` observability.
  - Hardened manifest/Qdrant fencing, replacement resume binding, tombstone-safe query preflight, and backfill control proofs with attempt-scoped points and crash resume.
  - Verification: `./.venv/bin/pytest -q` (**245 passed**); changed-file `py_compile`; `git diff --check`; final spec/ADR review approved.
  - Merged as PR #67 (`1ecc0b4`); GitHub closed #39 and #69.

- **Reviewed PR #67 against the persistent-graph handoff, linked issues, and ADR 0002**
  - Confirmed the persistent-artifact, manifest-CAS, tombstone-proof, generation-filter, and compatibility-fallback foundations are present.
  - Reported the unresolved handoff/ADR ownership conflict for #45–#46, missing implementation delivery issue/closing links, incomplete #39/#45/#46 acceptance criteria if retained in PR A, PR C tracking scope leakage, and non-hermetic backfill rejection tests.
  - Posted the evidence and required resolution to PR #67: https://github.com/amaldevice/graph-rag-summarizer/pull/67#issuecomment-4965454936
  - Verification: reviewed PR head `9ecf5eb`; clean-worktree `pytest -q` (`204 passed`); changed-file `py_compile`; `git diff --check`; isolated backfill-rejection tests fail without storage configuration (`ValueError: Invalid endpoint`).

## 2026-07-13

- **Prepared the PR #62 docs-only blocker patch for ADR 0002**
  - Updated `docs/adr/0002-persistent-document-graph-at-ingest.md` to make the lifecycle claim order explicit, fence Qdrant work with the manifest-issued token, define the tombstone deny control point and legacy-scan fail-closed rules, add monotonic version ledgering, and require gzip/canonical digest integrity checks on readers and writers.
  - Updated the issue-flow canvas (now archived at `docs/completed/canvas/issue-flow-architecture.html`) so ADR 0002 is clearly the decision record and PR #62 still needs a separate implementation delivery issue for PR A.
  - Updated `docs/todo-in-progress.md` to remove the docs-only item from In Progress and keep the overall handoff tracking intact.
  - PR #62 remains open pending independent review and merge.
  - Verification: `git diff --check`.

- **Aligned ADR 0002 with the collection-level active manifest contract for PR #62**
  - Updated `docs/adr/0002-persistent-document-graph-at-ingest.md` so the persistent artifact stays at `graphs/{collection}/{document_id}/v{version}/graph.json.gz` while the active manifest lives at `graphs/{collection}/manifest.json`.
  - Clarified that the manifest is collection-authoritative, readers resolve the per-document entry from the collection manifest, and each entry carries `document_id`, `active_version`, `active_artifact_key`, `status`, `backend`, `previous_pointer`, and `updated_at`.
  - Kept atomic activation, stale-write protection, and replacement semantics unchanged, and left the handoff untouched per request.
  - Verification: `git diff --check`.

- **Corrected the persistent graph ADR/PRD scope split for PR #62**
  - Added `docs/adr/0002-persistent-document-graph-at-ingest.md` as the lifecycle-only ADR for the ingest-stage graph artifact.
  - Narrowed the ADR to the exact artifact key, active manifest location and fields, available/partial/unavailable status semantics, append/replace/backfill behavior, atomic manifest activation, stale-write protection, and preservation of the previous active pointer on failed replacement.
  - Added the short PRD clarification that the launcher/operator contract and Query-Only behavior remain unchanged while the accepted ingest-stage graph artifact is optional and owned by ADR 0002.
  - Updated `docs/todo-in-progress.md` to track the docs-only fix.
  - Verification: focused markdown/reference review and `git diff --check`.

## 2026-07-12

- **Created the end-to-end implementation handoff for persistent graph construction**
  - Added `docs/completed/handoffs/handoff-2026-07-13-persistent-graph-implementation.md` with the target ingest/query flow, storage and lifecycle contract, PR A–D implementation sequence, issue/merge policy, desired outputs, verification contract, and suggested execution skills.
  - Referenced the adaptive graph PRD, ADR stack, Wayfinder map/decisions, and implementation issues without duplicating their canonical content.
  - Verification: handoff structure/reference check and `git diff --check`.

- **Recorded the accepted query-time adaptive context allocation policy**
  - Added `docs/adr/0005-query-time-adaptive-context-allocation.md` covering character budgets, community importance, minimum/maximum allocation, novelty selection, query protection, compatibility fallback, temporary multi-document views, and optional path signals.
  - Linked the decision to Wayfinder ticket #61 and the adaptive graph issue chain without changing runtime behavior.
  - Verification: ADR structure/reference check and `git diff --check`.

- **Recorded the accepted adaptive topology and stable community selection policy**
  - Added `docs/adr/0004-adaptive-topology-and-stable-community-selection.md` covering adaptive mutual-kNN topology, per-document graph-shape guardrails, multiresolution Leiden selection, ARI/NMI stability, and diagnostic-only embedding clustering.
  - Linked the decision to Wayfinder ticket #60 and the adaptive graph issue chain without changing runtime behavior.
  - Verification: ADR structure/reference check and `git diff --check`.


- **Recorded the accepted persistent document-scoped graph architecture**
  - Added `docs/adr/0002-persistent-document-graph-at-ingest.md` covering lifecycle/storage/fencing/backfill authority for the persistent document-scoped graph artifact, versioned object-storage artifacts, manifest activation, raw versus active relation evidence, stable ingest-time communities, failure handling, and legacy backfill boundaries. Adaptive query behavior stays with later work.
  - Kept PR #62 delivery split from the decision record so the implementation issue remains separate.
  - Confirmed the existing adaptive graph PRD and Wayfinder map/tickets remain the implementation planning surfaces; no duplicate spec or ticket set was created.
  - Verification: ADR structure/reference check and `git diff --check`.

- **Recorded the accepted bounded global relation recovery policy**
  - Added `docs/adr/0003-bounded-global-relation-recovery.md` covering document-scoped neighborhood candidates, bounded evidence-window verification, provider fallback, raw versus active edges, orphan diagnostics, and stable operational caps.
  - Linked the decision to Wayfinder ticket #59 and the existing adaptive graph issue chain without duplicating the PRD or tickets.
  - Verification: ADR structure/reference check and `git diff --check`.

- **Implemented issue #37 parent-child context expansion and issue #38 tiny sentence filtering**
  - Added stable section/paragraph/sentence IDs and bounded hierarchy paths during Docling chunking, including context-only parents for single-sentence chunks.
  - Added Qdrant parent retrieval with document-safe point IDs, partial/unavailable status reporting, legacy-payload fallback, and prompt/artifact parent-context visibility.
  - Excluded context-only parents from entity/graph/pruner selection while retaining them for bounded context recovery.
  - Added the 8-word sentence filter with section/title exemption and observable filtered-chunk records without changing path-aware score calculation.
  - Verification: `uv run pytest -q` (`171 passed`); targeted hierarchy/Qdrant/ingest suite (`38 passed`); `py_compile`; `git diff --check`.

- **Created a compact starter architecture guide for new agents**
  - Added `docs/ONBOARDING_STARTER_ARCHITECTURE.md` with the project mental model, technology stack, launcher modes, ingest and Full-Pipeline flows, source map, core data contracts, onboarding order, and current GraphRAG boundaries.
  - Kept the guide aligned with the existing single-launcher/Qdrant architecture and explicitly documented that graph construction is currently query-time, not persisted during ingest.
  - Verification: validated 17 referenced paths, `uv run pytest -q` (`161 passed`), and `git diff --check`.

- **Created an issue-to-flow architecture docs canvas**
  - Added the issue-flow architecture canvas (now archived at `docs/completed/canvas/issue-flow-architecture.html`) with then-current PR/issue status, before/after flow comparisons, issue dependency graph, blocker semantics, and detailed stage-by-stage architecture impact.
  - Covered the active PR #53, staged #12 delivery, closed parent issues #25/#33, and open adaptive graph chain #44–#52.
  - Verification: Python HTML parser smoke test, internal-anchor validation, `git diff --check`, and local HTTP server/curl render check.

## 2026-07-12

- **Implemented document-safe PDF ingest modes for shared Qdrant collections (issue #12)**
  - Added stable document IDs and deterministic UUID point IDs while preserving local chunk order in payload metadata.
  - Added `append`, `replace-document`, and `replace-collection` lifecycle modes to the launcher and legacy upload wrapper.
  - Added document-aware retrieval and graph/pruner handoff metadata, including repeated local-ID protection across documents.
  - Added mixed-document page-image safeguards and warnings for unavailable or ambiguous local PDF enrichment.
  - Updated README, runbook, and environment examples with the new ingest contract.
  - Verification: `uv run pytest -q` (`161 passed`); targeted ingest/graph suite (`76 passed`); `py_compile`; `git diff --check`.

## 2026-07-11

- **Committed the requested active-docs guidance in `AGENTS.md`**
  - Added the repository rule that in-progress documentation stays under `docs/` and is not placed in `docs/completed/`.
  - Verification: reviewed the one-line `AGENTS.md` diff and confirmed no unrelated files were staged.

- **Kept the Issue #44 planning artifacts active in the root `docs/` area**
  - Moved the PRD and published slice breakdown out of the completed archive because Issue #44 and its implementation program remain active.
  - Archived after delivery: `docs/completed/prd/prd-2026-07-11-adaptive-global-graph-construction.md` and `docs/completed/issues/slice-2026-07-11-adaptive-global-graph-construction.md`.
  - Verification: confirmed both active paths exist, both archived paths are absent, and `git diff --check` passes.

- **Finalized Issue #44 as a repo-local PRD and published eight vertical slices**
  - Added the complete adaptive global graph construction PRD with 48 user stories, explicit boundaries around issues #39 and #40, implementation decisions, and a Full-Pipeline-first testing strategy.
  - Published ready-for-agent issues #45 through #52 for auditable relation evidence, entity canonicalization and orphan diagnostics, bounded global candidates, verified graph recovery, adaptive semantic topology, multiresolution community selection, embedding-clustering diagnostics, and adaptive context allocation.
  - Recorded each issue's blocking edges and kept #45 and #49 as the initial parallel execution frontier.
  - Kept the PRD and slice breakdown active under the root `docs/` area while Issue #44 and its child implementation issues remain open.
  - Verification: `gh issue view 44`; `gh issue view 39`; `gh issue view 40`; `gh issue view 45` through `52`; all child issues are open and labeled `ready-for-agent`; markdown structure check found all required PRD sections, 48 user stories, 8 tickets, and 61 acceptance criteria; `git diff --check`.

## 2026-07-07

- **Moved `$teach` materials to local-only workspace state**
  - Removed `MISSION.md`, `RESOURCES.md`, `NOTES.md`, `assets/`, `lessons/`, and `reference/` from the tracked git index while preserving the local files on disk.
  - Added those teaching workspace paths to `.gitignore` so they stay out of the remote repository going forward.
  - Verification: `git check-ignore -v` confirms the teaching files are ignored, and `find` confirms the local lesson/reference files still exist.

- **Created beginner-friendly Flow Project teaching materials**
  - Added a teaching mission, resources, and notes for learning how the GraphRAG Summarizer flow turns a PDF into a final evaluated summary.
  - Added `lessons/0001-flow-project-overview.html` as a beginner-friendly walkthrough of every flowchart stage, including what each stage does plus its input and output.
  - Created `reference/flow-project-cheatsheet.html`, shared `assets/lesson.css`, and a local copy of the flowchart image for quick review and printable reference.
  - Verification: inspected the flowchart image, reviewed current implementation anchors in `launcher/runners.py`, `graph/graph_builder.py`, `summarizer/pruner.py`, and `docs/handoff-2026-07-06-flow-project-next-development.md`; ran an HTML parser smoke check for the lesson and reference files.

- **Published the lightweight grounded evaluation metrics follow-up issue**
  - Created GitHub issue `#43` — `Add lightweight grounded evaluation metrics without heavy models` — for entity consistency, number/date consistency, sentence support, citation coverage, redundancy, query relevance, and evidence diversity.
  - Updated `docs/handoff-2026-07-06-flow-project-next-development.md` so the evaluation-layer partial block points to `#43` as the cheaper first pass and keeps `#35` for heavier FactCC/SummaC adapters.
  - Verification: `gh issue view 43` confirmed the ready-for-agent issue includes pros, cons, step-by-step flow, acceptance criteria, and no-new-required-dependency scope.

- **Published ready-for-agent issues for the remaining Flow Project partial blocks**
  - Created GitHub issues `#36` through `#42` for the yellow/partial flowchart blocks that did not already have a dedicated follow-up tracker.
  - Covered table/figure evidence, parent-child hierarchy expansion, tiny sentence filtering, hybrid entity/relation extraction hardening, PathRAG-grade path scoring, embedding-aware RAPTOR grouping, and forced-fail feedback-loop smoke verification.
  - Updated `docs/handoff-2026-07-06-flow-project-next-development.md` so every partial block now points to its tracking issue, including existing SummaC/FactCC issue `#35`.
  - Verification: `gh issue view` confirmed issues `#36`-`#42` are open, labeled `ready-for-agent`, and include pros, cons, and step-by-step flow sections.

- **Expanded the Flow Project next-development handoff partial-block guidance**
  - Updated `docs/handoff-2026-07-06-flow-project-next-development.md` with per-block notes for every yellow/partial flowchart area.
  - Added why each block is not full research-grade yet, step-by-step implementation notes, pros/cons, and expected impact on the current flow/output.
  - Linked the optional SummaC/FactCC work back to issue `#35` so the next agent has a concrete tracker.
  - Verification: reviewed the updated handoff section and confirmed the required partial-block guidance is present.

- **Published the optional SummaC/FactCC evaluation follow-up issue**
  - Created GitHub issue `#35` — `Wire optional SummaC and FactCC grounded evaluation adapters` — as the next-development tracker for upgrading the current unavailable placeholder metrics into optional grounded evaluators.
  - Included pros/cons, risks, step-by-step flow integration, acceptance criteria, and current implementation seams for the next agent.
  - Kept the issue scoped to optional adapters so normal Query-Only, Ingest, and Full-Pipeline Runs do not gain mandatory heavy research dependencies.
  - Verification: reviewed `evaluation/evaluator.py`, `evaluation/quality_checker.py`, `tests/test_flowchart_alignment.py`, searched existing FactCC/SummaC issues, and verified `gh issue view 35` returns the expected ready-for-agent issue.

## 2026-07-06

- **Captured Flow Project next-development notes**
  - Added `docs/handoff-2026-07-06-flow-project-next-development.md` as a lightweight markdown note instead of opening another PRD/issue, because this is a development memory note rather than approved implementation scope.
  - Summarized the current flowchart alignment status, added the flowchart status table, latest run evidence, remaining partial areas, and the recommended next small slice: tiny sentence chunk filtering.
  - Verification: reviewed the latest artifact summary from `output/full_pipeline_2026-07-06T13-51-43-901349Z` already analyzed in-thread and saved the note under the required handoff naming prefix.

- **Implemented Qdrant-safe batched uploads for large Ingest Runs (issue #34)**
  - Changed Qdrant chunk uploads to write bounded batches instead of one oversized request, preserving the existing Ingest Run launcher flow.
  - Kept hierarchy/layout/image payload metadata intact while allowing large hierarchy-aware chunk sets to fit within Qdrant Cloud request-size limits.
  - Added regression coverage proving large fake uploads split into multiple Qdrant upsert calls.
  - Verification: `uv run pytest -q tests/test_qdrant_handler_cloud.py tests/test_ingest_runner.py tests/test_flowchart_alignment.py`; `uv run python -m py_compile vectordb/qdrant_handler.py tests/test_qdrant_handler_cloud.py`; `uv run pytest -q` (`146 passed`).

- **Published the Qdrant-safe batched Ingest Runs PRD and implementation slice**
  - Captured the observed Qdrant Cloud upload failure where a hierarchy-aware Ingest Run produced 6,634 chunks and attempted a single ~110 MB JSON payload against a ~32 MB request limit.
  - Published GitHub issue `#33` as the parent PRD for bounded Qdrant upload batches in Ingest Runs.
  - Published GitHub issue `#34` as the single ready-for-agent implementation slice because the smallest complete fix lives at the vector store upload seam.
  - Archived the local PRD and slice notes under `docs/completed/prd/` and `docs/completed/issues/`.
  - Verification: reviewed `launcher/runners.py`, `vectordb/qdrant_handler.py`, `tests/test_qdrant_handler_cloud.py`, `tests/test_ingest_runner.py`, and current Qdrant client upsert signature; `gh issue create` for `#33` and `#34`; parent issue comment linking the child slice.

- **Implemented flowchart-aligned Full-Pipeline Runs end-to-end (issues #26-#31)**
  - Added hierarchy/layout chunk metadata from Docling ingest through Qdrant payload normalization, while keeping older payloads readable.
  - Added chunk-entity mention edges plus path-aware pruning artifacts with path evidence, semantic retrieval score, centrality score, and community-bounded top-k selection.
  - Updated map and reduce prompts with explicit NAP/CAP/CGM instructions and selected evidence metadata.
  - Added RAPTOR-style multi-level reduction for larger community sets using the existing embedding runtime, with single-merge fallback for small runs.
  - Added grounded evaluation metric status objects for FactCC, SummaC, G-Eval, and QA coverage; missing optional evaluators report unavailable instead of crashing.
  - Closed the feedback loop inside Full-Pipeline Runs with bounded automatic reruns from retrieval, prompt, or reduction, plus per-attempt artifacts.
  - Added regression coverage in `tests/test_flowchart_alignment.py` and updated existing Qdrant payload assertions.
  - Verification: `uv run pytest -q tests/test_flowchart_alignment.py tests/test_qdrant_handler_cloud.py tests/test_ingest_runner.py tests/test_full_pipeline_shared_session_wiring.py tests/test_shared_session.py tests/test_embedding_entrypoints.py`; `uv run pytest -q tests/test_flowchart_alignment.py tests/test_full_pipeline_dispatch.py tests/test_launcher_contract.py tests/test_launcher_main.py tests/test_query_only_runner.py tests/test_qdrant_handler_backends.py tests/test_docling_loader_storage_contract.py tests/test_text_embedder_runtime.py tests/test_provider_router.py`; `uv run python -m py_compile launcher/runners.py preprocessing/docling_loader.py vectordb/qdrant_handler.py graph/graph_builder.py summarizer/pruner.py summarizer/prompt_builder.py summarizer/hierarchical_reducer.py evaluation/evaluator.py evaluation/quality_checker.py pipeline/feedback_loop.py tests/test_flowchart_alignment.py tests/test_qdrant_handler_cloud.py`; `uv run pytest -q` (`145 passed`).

- **Published the flowchart-aligned Full-Pipeline PRD and approved child issue slices**
  - Created GitHub issue `#25` for the PRD covering hierarchy-aware chunking, path-aware pruning, NAP/CAP/CGM prompts, RAPTOR-style reduction, grounded evaluation signals, and bounded adaptive feedback reruns.
  - Published approved vertical slices as issues `#26` through `#31` in dependency order.
  - Archived the finalized local PRD and slice breakdown under `docs/completed/prd/` and `docs/completed/issues/`.
  - Verification: `gh issue view 25`; `gh issue create` for issues `#26`-`#31`; parent issue comment linking the child slice chain.

- **Compared the project flow against the provided GraphRAG summarization flowchart**
  - Inspected the provided WhatsApp flowchart image and matched it against the current ingest, retrieval, graph, summarization, evaluation, and feedback modules.
  - Confirmed the project is broadly aligned from Docling ingest through Qdrant retrieval, graph/community ranking, map/reduce summarization, quality gate, and feedback decision output.
  - Identified partial gaps: chunking is Docling-item/fallback paragraph based rather than explicit sentence→paragraph→section hierarchy; default embedding is `nomic-ai/nomic-embed-text-v1.5`, not BGE-M3/Sentence-BERT; evaluation is ROUGE/BERTScore when reference exists or lexical overlap without reference, not FactCC/SummaC/G-Eval/QA coverage; feedback writes a retry decision but does not automatically loop back and rerun the corresponding stage.
  - Verification: inspected `WhatsApp Image 2026-06-25 at 20.20.50.jpeg`; reviewed `README.md`, `launcher/runners.py`, `upload_to_qdrant.py`, `preprocessing/docling_loader.py`, `preprocessing/image_exporter.py`, `embedding/embedder.py`, `vectordb/qdrant_handler.py`, `graph/*`, `summarizer/*`, `evaluation/*`, and `pipeline/feedback_loop.py` with `rg`/line-numbered static review.

- **Shipped artifact-directory Full-Pipeline Runs plus stage-aware launcher logging (PRD #22, issue #23)**
  - Replaced the misleading Full-Pipeline `json_output` flow with an explicit `artifact_dir` contract in `launcher/contract.py` and preserved that value through the launcher edit loop in `main.py`.
  - Added a collision-resistant per-run default artifact directory and mode-aware summary rendering so Query-Only Run still shows one JSON artifact while Full-Pipeline Run shows its artifact directory.
  - Added stage/state progress output plus one shared `verbose` toggle across Query-Only Run, Ingest Run, and Full-Pipeline Run in `launcher/runners.py`.
  - Routed every Full-Pipeline artifact writer into the selected artifact directory without changing the existing artifact basenames.
  - Expanded regression coverage for launcher contract defaults/prompts, stage markers, main-loop config preservation, and artifact-directory forwarding across the full-pipeline seam.
  - Archived the local planning docs to `docs/completed/prd/` and `docs/completed/issues/` after implementation.
  - Verification: `uv run pytest -q tests/test_launcher_contract.py tests/test_query_only_runner.py tests/test_ingest_runner.py tests/test_full_pipeline_shared_session_wiring.py tests/test_launcher_main.py`; `uv run python -m py_compile main.py launcher/contract.py launcher/runners.py tests/test_launcher_contract.py tests/test_query_only_runner.py tests/test_ingest_runner.py tests/test_full_pipeline_shared_session_wiring.py tests/test_launcher_main.py`; `uv run pytest -q` (`133 passed`).

## 2026-07-05

- **Published the launcher artifact-directory + stage-aware logging planning set**
  - Wrote `docs/prd-2026-07-05-launcher-artifact-directory-and-stage-aware-logging.md` and published it as GitHub issue `#22`.
  - Wrote `docs/issue-2026-07-05-launcher-artifact-directory-and-stage-aware-logging.md` and published it as GitHub issue `#23`.
  - Locked the approved scope: Artifact output directory applies to Full-Pipeline Runs only, while one shared verbose toggle plus stage/state output applies across Query-Only, Ingest, and Full-Pipeline modes.
  - Kept the first pass intentionally narrow: no log files, no artifact renaming, no Query-Only output-directory rewrite, and no new slice breakdown beyond the single ready-for-agent implementation issue.
  - Verification: reviewed `launcher/contract.py`, `launcher/runners.py`, `tests/test_launcher_contract.py`, `tests/test_query_only_runner.py`, `tests/test_ingest_runner.py`, and `tests/test_full_pipeline_dispatch.py`; `gh issue create --title "PRD: artifact-directory Full-Pipeline Runs and stage-aware launcher logging" ...`; `gh issue create --title "Ship artifact-directory Full-Pipeline Runs and stage-aware launcher logging" ...`; `gh issue view 22`; `gh issue view 23`.

- **Fixed the Groq full-pipeline crash without dropping Groq from the provider contract**
  - Re-labeled GitHub issue `#21` from `enhancement` to `bug` and kept it as the implementation tracker for the Groq/httpx compatibility failure.
  - Replaced the native `groq` SDK construction path in `summarizer/provider_router.py` and `graph/entity_extractor.py` with the OpenAI-compatible client path pointed at `https://api.groq.com/openai/v1`.
  - Added `GROQ_BASE_URL` to `config/settings.py` and `env.example` so the Groq transport shape is explicit and configurable.
  - Added regression coverage in `tests/test_groq_openai_compat.py` and extended `tests/test_provider_router.py` so Groq now fails closed when `GROQ_BASE_URL` is blank.
  - Verification: `uv run python -m py_compile config/settings.py summarizer/provider_router.py graph/entity_extractor.py tests/test_groq_openai_compat.py tests/test_provider_router.py`; `uv run pytest -q tests/test_groq_openai_compat.py tests/test_provider_router.py`; `uv run pytest -q` (`130 passed`).

- **Published a tracking issue for the Groq full-pipeline compatibility fix**
  - Created GitHub issue `#21` — `Stabilize Groq full-pipeline runs with the OpenAI-compatible client path`.
  - Captured the observed Full-Pipeline Run failure, the diagnosed `groq==0.9.0` vs `httpx==0.28.1` compatibility mismatch, the alternative fix options, and the currently chosen OpenAI-compatible Groq direction.
  - Published the issue as `enhancement` + `ready-for-agent` so it can serve as the implementation log and next execution target.
  - Verification: `gh issue view 21 --json number,title,labels,url,body`.

- **Tidied the `docs/` structure**
  - Moved completed handoffs, PRDs, and slice docs out of the active `docs/` root and into `docs/completed/handoffs/`, `docs/completed/prd/`, and `docs/completed/issues/`.
  - Moved the launcher runbook into `docs/runbook-single-launcher.md` and removed the stray `docs/.DS_Store` file.
  - Reduced the active `docs/` root to the still-relevant backlog/runbook files while leaving the supporting agent, ADR, and superpowers reference docs in place.
  - Verification: reviewed the post-move `docs/` tree and checked archived handoff links that still needed updated archive paths.

- **Added a compact single-launcher runbook**
  - Added `docs/runbook-single-launcher.md` to explain the real `main.py` execution flow, the profile/mode split, interactive vs non-interactive behavior, and the available CLI arguments.
  - Kept the guide compact and aligned it to the current launcher contract instead of duplicating older planning language.
  - Included concrete example commands plus current runtime notes for cloud profile, local embedding execution, connection checks, and the current one-PDF-per-collection safety recommendation.
  - Verification: reviewed `launcher/contract.py` and `launcher/runners.py` against the runbook; `uv run python - <<'PY' ... Path('docs/runbook-single-launcher.md').read_text() ... PY` confirmed the doc includes the shipped modes and argument names.

- **Added a cloud environment template and standalone cloud connection checks**
  - Added `.env.cloud` as a cloud-oriented template for Qdrant Cloud, Cloudflare R2, LLM providers, and the default embedding runtime.
  - Added `scripts/check_cloud_connections.py` so R2 and Qdrant Cloud connectivity can be tested without going through `main.py`.
  - Added `tests/test_cloud_connection_check.py` to keep the standalone checker from drifting.
  - Verification: `uv run python -m py_compile scripts/check_cloud_connections.py tests/test_cloud_connection_check.py`; `uv run python scripts/check_cloud_connections.py --help`; `uv run pytest -q tests/test_cloud_connection_check.py` (3 passed).
- **Reviewed and shipped draft PR #20 for the launcher + multi-provider branch**
  - Re-ran targeted compile checks for the launcher and provider-router seams.
  - Re-ran the full test suite and confirmed `124` tests pass before merge.
  - Re-checked the draft PR state, verified there were no reported GitHub checks to wait on, and confirmed the linked implementation issues were ready to close on merge.
  - Merged PR `#20`, closed issues `#17`, `#18`, and `#19`, and deleted the feature branch after the merge.
  - Verification: `uv run python -m py_compile launcher/contract.py launcher/runners.py summarizer/provider_router.py summarizer/llm_summarizer.py summarizer/hierarchical_reducer.py tests/test_provider_router.py tests/test_shared_session.py tests/test_full_pipeline_shared_session_wiring.py tests/test_full_pipeline_dispatch.py tests/test_launcher_contract.py tests/test_embedding_entrypoints.py`; `uv run pytest -q` (124 passed).

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
  - Added `docs/prd-2026-07-04-cross-platform-local-embedding-runtime.md`, `docs/completed/superpowers/plans/2026-07-04-cross-platform-local-embedding-runtime.md`, and `docs/slice-2026-07-04-cross-platform-local-embedding-runtime.md`.
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
