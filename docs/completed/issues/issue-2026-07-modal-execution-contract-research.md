# Research: Modal execution contract for each Launcher Mode

**Status:** resolved
**Tracker:** [Research: establish Modal execution contract for each Launcher Mode](https://github.com/amaldevice/graph-rag-summarizer/issues/93)

## Decision

Keep the launcher/wizard on the operator machine. A Modal Function receives a
structured, non-interactive request and runs existing runner logic. This is a
new Compute Backend; it does not change the meaning of the existing Launch
Profile.

| Launcher Mode | Initial Modal contract |
| --- | --- |
| Ingest Run | `modal run` calls a local entrypoint, which stages the PDF and invokes one remote GPU-capable Function. |
| Query-Only Run | `modal deploy` creates a named deployed App; the local wizard looks up and calls its deployed Function for each query. |
| Full-Pipeline Run | `modal run` calls a local entrypoint and one long-timeout remote Function. Split later only when measured resource or retry requirements differ. |

`modal run` creates an ephemeral App, so it fits operator-triggered batch work.
Repeated queries must call a deployed Function explicitly (Python client or an
authenticated web endpoint); they must not create a fresh ephemeral App for
every request. A public web endpoint is not part of the initial design.

## Remote boundary

- Pass small serializable request data directly; never pass a laptop path.
- For a PDF, stage bytes under a unique Modal Volume key or pass an existing R2
  object key. The Function materializes it to a container-local temporary path.
- Inject Qdrant, R2, and LLM credentials with named Modal Secrets. Do not pass
  `.env` data, credentials, or secrets as arguments or log them.
- Use a Volume for model cache and non-authoritative run artifacts. Call
  `volume.commit()` after writing ordinary output before the Function returns.
- Keep the persistent graph manifest and graph blobs on R2. They require
  conditional CAS/fencing under ADR 0002; a Modal Volume has last-writer-wins
  file semantics and cannot be the graph lifecycle authority.
- Treat non-mounted container paths as scratch only. Return persistent artifact
  locations, not container paths.

## GPU and image policy

GPU is selected per Function, not automatically. Start benchmarking Ingest with
an inference-appropriate GPU such as L40S, but choose the final class only from
representative document measurements. Put Hugging Face/model caches on a named
Volume and load a reused model per warm container. The current code first needs
explicit CUDA support: it accepts `auto|cpu|mps` only, and Linux `auto` resolves
to CPU.

Set explicit Full-Pipeline timeouts; Modal's default Function timeout is five
minutes. Use a minimal explicit Image, adding a CUDA development base only if a
dependency actually requires the CUDA toolkit.

## Constraints preserved

- `profile=cloud` remains Qdrant Cloud + R2, never a synonym for Modal.
- Ingest still executes the existing document-safe claim, fence, manifest, and
  idempotency lifecycle from ADR 0002.
- External LLM providers remain external APIs; a Modal GPU does not accelerate
  their network calls.

## Official sources

- [Apps](https://modal.com/docs/guide/apps)
- [`modal run`](https://modal.com/docs/cli/latest/run)
- [Deployments](https://modal.com/docs/guide/managing-deployments) and [invoking deployed Functions](https://modal.com/docs/guide/trigger-deployed-functions)
- [Passing local data](https://modal.com/docs/guide/local-data)
- [Volumes](https://modal.com/docs/guide/volumes) and [Cloud bucket mounts](https://modal.com/docs/guide/cloud-bucket-mounts)
- [Secrets](https://modal.com/docs/guide/secrets), [timeouts](https://modal.com/docs/guide/timeouts), and [security/privacy](https://modal.com/docs/guide/security)
- [GPU acceleration](https://modal.com/docs/guide/gpu), [CUDA](https://modal.com/docs/guide/cuda), [model weights](https://modal.com/docs/guide/model-weights), and [lifecycle functions](https://modal.com/docs/guide/lifecycle-functions)
