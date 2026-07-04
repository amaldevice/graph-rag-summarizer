# PRD — dual local/cloud ingest for graph-rag-summarizer

Date: 2026-07-04
Status: Drafted for execution

## Problem Statement

The project's ingest path currently behaves as a cloud-first path. Object storage is wired to R2, Qdrant selection is only implicit, and the local Docker stack for MinIO plus local Qdrant is partially orphaned. That makes it harder to switch between local development and cloud operation without code edits, even though the downstream summarization pipeline should stay exactly the same.

## Solution

Support one ingest flow that selects infrastructure by environment:

- local mode uses persisted local Docker volumes with MinIO and local Qdrant
- cloud mode uses the existing R2 bucket and existing Qdrant Cloud instance

The ingest flow keeps the same downstream chunk contract, so retrieval, graph analysis, summarization, evaluation, and feedback logic do not need to change.

## User Stories

1. As a developer, I want to run ingest locally against MinIO and local Qdrant, so that I can iterate without cloud dependencies.
2. As a developer, I want local Docker volumes to retain MinIO and Qdrant state, so that I do not need to rebuild storage state every run.
3. As an operator, I want cloud mode to keep using the existing R2 bucket and Qdrant Cloud instance, so that current hosted workflows keep working.
4. As a developer, I want backend switching to happen through environment variables, so that I do not need to edit source code per environment.
5. As a maintainer, I want the ingest flow to stay single-path, so that local and cloud mode do not drift into separate implementations.
6. As a maintainer, I want the document loader to be storage-backend-neutral, so that image upload behavior can change without touching chunking logic.
7. As a maintainer, I want Qdrant backend selection to be explicit, so that local, cloud, and fallback behavior are easy to reason about.
8. As a downstream consumer, I want chunk payload fields to stay stable, so that retrieval and summarization do not break when storage backends change.
9. As a tester, I want the current cloud behavior locked by regression tests, so that backend refactors do not silently break the working path.
10. As a tester, I want small targeted tests around storage selection and Qdrant mode selection, so that backend mistakes fail fast.
11. As an operator, I want environment examples for both local and cloud modes, so that setup is predictable.
12. As a maintainer, I want backend-neutral smoke script wording, so that local-only and cloud-only names do not become misleading.
13. As a collaborator, I want the local compose stack to be useful again, so that the repo’s documented local path matches live code behavior.
14. As a maintainer, I want this work tracked in docs and GitHub issues, so that later handoff does not depend on chat history.
15. As a reviewer, I want the implementation delivered as a PR instead of direct mainline changes, so that the backend transition can be reviewed before merge.

## Implementation Decisions

- Keep one ingest pipeline and make backend selection an environment concern rather than a separate pipeline concern.
- Add explicit selectors for object storage and Qdrant backend mode.
- Keep the current cloud-first behavior as the safe default.
- Use a thin storage-selection layer with two concrete handlers: R2 for cloud mode and MinIO for local mode.
- Make the document loader depend on the active storage handler surface instead of directly naming R2.
- Make Qdrant mode explicit as local, cloud, or automatic fallback, while preserving the current automatic behavior as the default.
- Preserve the retrieved chunk contract: `chunk_id`, `text`, `level`, `source`, `page_no`, `image_url`, plus retrieval-time `score` and `rank`.
- Preserve page alias compatibility where needed, but normalize downstream behavior around `page_no`.
- Keep local mode aligned with persisted Docker volumes rather than ephemeral bootstrap-only infrastructure.
- Update environment documentation to show both local and cloud profiles.
- Keep smoke/integration naming backend-neutral where the old R2-only wording would be misleading.
- Do not change downstream graph, summarizer, evaluation, or feedback-loop behavior in this pass.

## Testing Decisions

- Good tests should verify observable behavior and payload stability, not internal implementation details.
- Reuse the highest seams already present: handler-level tests for storage behavior and Qdrant payload behavior.
- Add narrow tests for storage backend selection, document-loader storage usage, and explicit Qdrant mode selection.
- Keep the existing cloud-path tests as regression gates.
- Verify Python behavior through the repository’s Colab CLI path instead of local host Python.
- Verify local infrastructure changes with Docker Compose validation and, if needed, a small local smoke check.
- Prior art already exists in the current storage URL/upload test and the current Qdrant payload-normalization test.

## Execution Checklist

1. Add a tiny targeted pytest launcher for the Colab CLI path.
2. Add explicit storage and Qdrant backend selectors to environment-backed settings.
3. Add thin MinIO plus storage-selection support without forking the ingest pipeline.
4. Make the document loader storage-backend-neutral.
5. Make Qdrant backend mode explicit while preserving payload normalization.
6. Revive the local Docker path and make docs plus smoke naming backend-neutral.

## Out of Scope

- Changing the downstream summarization, graph analysis, evaluation, or feedback-loop pipeline.
- Replacing Docling, Qdrant, MinIO, or R2 with different products.
- Adding a third storage backend or a third vector database mode.
- Reworking the chunking strategy beyond what is needed for backend neutrality.
- Adding CI/CD automation or deployment orchestration in this pass.

## Further Notes

- Local mode should rely on persisted local Docker volumes.
- Cloud mode should keep using the already-provisioned R2 and Qdrant Cloud resources.
- The implementation should land as a PR for review before merge, not as direct mainline changes.
