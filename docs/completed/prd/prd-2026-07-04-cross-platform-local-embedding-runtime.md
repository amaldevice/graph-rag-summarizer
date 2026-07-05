# PRD — cross-platform local embedding runtime for graph-rag-summarizer

Date: 2026-07-04
Status: Drafted for execution

## Problem Statement

The repository currently assumes one local embedding runtime path: `sentence-transformers` instantiated directly with no explicit backend, device, cache policy, or cross-platform fallback contract. That is acceptable for one maintainer on one machine, but it becomes fragile once the repository is forked by Windows, Linux, or macOS users with different hardware capabilities.

Today there is no single documented rule for:

- when macOS should prefer MPS versus CPU,
- how Windows and Linux should behave by default,
- how an optional ONNX path should be enabled safely,
- where local embedding artifacts should be cached,
- how ingest and query guarantee they still use the same embedding model,
- and how the runtime should explain fallback behavior when a requested accelerator is unavailable.

That makes the local embedding path harder to reproduce, harder to support, and easier to break silently across forks.

## Solution

Add one shared embedding runtime contract that resolves local embedding behavior by configuration plus host capability detection.

The default path stays conservative and cross-platform:

- `sentence_transformers` remains the primary backend,
- macOS prefers `mps` and falls back to `cpu`,
- Windows and Linux default to `cpu`,
- ONNX is optional and experimental,
- all local embedding artifacts live under project-local `.cache/embedding/`,
- and ingest plus query must continue using the same `EMBEDDING_MODEL` even when backend or device selection changes.

The runtime must log the requested backend/device, detected platform, resolved backend/device, and any fallback reason so users can understand what actually ran on their machine.

## User Stories

1. As a macOS user, I want local embedding to prefer MPS automatically when it is available, so that I can use Apple GPU acceleration without manual setup.
2. As a macOS user, I want the runtime to fall back to CPU cleanly when MPS is unavailable, so that the pipeline still runs.
3. As a Windows user, I want the repository to default to a safe CPU path, so that I can run the project without debugging unsupported accelerator logic.
4. As a Linux user, I want the repository to default to a safe CPU path, so that local execution works on generic machines.
5. As a maintainer, I want backend and device configuration to be explicit, so that runtime behavior is easy to reason about.
6. As a maintainer, I want runtime resolution centralized in one helper, so that ingest and query do not drift.
7. As a maintainer, I want ONNX to be optional instead of the default, so that the main path stays stable for most users.
8. As a power user, I want to opt into ONNX locally, so that I can experiment with a faster or more specialized inference path.
9. As a user choosing ONNX, I want the runtime to prepare required local artifacts lazily on first run, so that I do not need a separate manual export workflow.
10. As a user choosing ONNX, I want unsupported or missing ONNX prerequisites to degrade with a clear warning, so that the pipeline still works.
11. As a maintainer, I want ONNX support limited to a tested allowlist at first, so that cross-platform support remains manageable.
12. As a maintainer, I want fallback from ONNX to preserve the same embedding model whenever possible, so that retrieval quality does not change silently.
13. As a user, I want downloaded model weights and exported ONNX artifacts stored locally under the project root, so that cleanup is simple and nothing large needs to be committed.
14. As a maintainer, I want `.cache/embedding/...` ignored by Git, so that remote repositories stay small and clean.
15. As a downstream user, I want ingest and query to use the same embedding model contract, so that vectors remain comparable.
16. As a maintainer, I want runtime startup logs to report requested versus resolved behavior, so that bug reports contain actionable context.
17. As a tester, I want resolver behavior covered by targeted tests, so that platform-specific regressions fail fast.
18. As a collaborator, I want setup docs to explain the default runtime and the optional ONNX path clearly, so that forks can adopt the project without reading chat history.
19. As a maintainer, I want the default dependency install to stay lightweight, so that optional ONNX packages do not burden users who only need the default path.
20. As a reviewer, I want the work split into AFK-agent-ready slices, so that the implementation can be executed and reviewed incrementally.

## Implementation Decisions

- Keep one `TextEmbedder` entrypoint and move backend/device selection behind a shared runtime resolver instead of branching separately in ingest and query code.
- Split embedding configuration into explicit backend and device controls.
- Keep the default backend as `sentence_transformers`.
- Keep ONNX as optional and experimental in the first pass.
- Restrict automatic OS/hardware detection to the embedding runtime only; do not let it influence storage, Qdrant, or summarization configuration.
- Use conservative defaults: macOS prefers MPS if available, otherwise CPU; Windows and Linux default to CPU.
- Emit clear startup logs for requested and resolved backend/device plus fallback reasons.
- Keep embedding model identity stable across ingest and query; runtime selection may change, but `EMBEDDING_MODEL` must remain the same.
- Store downloaded embedding weights and generated ONNX artifacts under project-local `.cache/embedding/` rather than in tracked repository files.
- Do not introduce a user-facing cache-directory override in the first pass.
- Keep ONNX support limited to a tested allowlist initially, starting with the repository's default embedding model.
- If ONNX is requested but unavailable or unsupported, warn clearly and fall back to the standard `sentence_transformers` path.
- When ONNX falls back, preserve the same embedding model if the standard runtime can still load it.
- Keep the default installation path free of optional ONNX dependencies; install those through a separate dependency group.
- Prefer the shortest implementation path that preserves the stable default runtime for existing users.

## Testing Decisions

- Good tests should verify observable runtime behavior: resolved backend/device, fallback rules, cache-path decisions, and embedder contract stability.
- The highest seam is the shared runtime resolver plus the public `TextEmbedder` entrypoint; test there before adding lower-level implementation-specific tests.
- Add targeted tests for macOS MPS preference, Windows/Linux CPU defaults, ONNX warning fallback, allowlist enforcement, and shared-model contract preservation.
- Keep one or two thin entrypoint tests around ingest and query wiring to prove they both use the same runtime contract.
- Prefer monkeypatched capability detection over true multi-OS execution in unit tests.
- Keep any ONNX tests lightweight and contract-focused; do not require heavy live exports in the default fast test path.
- Add a small documentation-facing verification step so README examples continue matching the actual config contract.

## Out of Scope

- Changing the retrieval, graph, summarization, evaluation, or feedback-loop logic beyond what is necessary to keep embedding configuration coherent.
- Auto-detecting CUDA, ROCm, DirectML, or other non-Apple accelerator paths in the first pass.
- Making ONNX the default runtime.
- Adding cloud-hosted embedding inference.
- Introducing user-configurable cache roots in the first pass.
- Broadly reworking repository structure outside the embedding runtime path.

## Further Notes

- The repo is now managed by `uv`, so any optional ONNX dependency path should align with `uv` dependency groups.
- Cross-platform support should optimize for predictability first and speed second.
- The first execution milestone should make the default path robust on all supported OSes and make the MPS path work end-to-end on macOS. ONNX can remain optional and staged.
