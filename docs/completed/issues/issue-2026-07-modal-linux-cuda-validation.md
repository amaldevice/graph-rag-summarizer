# Validation: Modal Linux CUDA image and remote Ingest safety

**Status:** resolved
**Tracker:** [Task: validate Modal Linux CUDA image and remote ingest safety](https://github.com/amaldevice/graph-rag-summarizer/issues/96)

## Result

The first Modal delivery slice is technically viable: a Modal Linux image can
use an L4 GPU, read the configured Qdrant Cloud/R2 authority through a named
Modal Secret, stage a PDF on a temporary Volume, and run the locked project's
Docling and embedding dependencies. This task did not implement the Modal
backend or mutate production data planes.

## Evidence

| Check | Observed result |
| --- | --- |
| Modal GPU | Linux worker reported NVIDIA L4, CUDA 13.0, and `torch 2.13.0+cu130`. |
| PDF staging and Docling | A 1,339,993-byte PDF was staged into a temporary Volume and converted into 732 chunks. |
| Locked project image | Project imports and direct `nomic-ai/nomic-embed-text-v1.5` SentenceTransformer inference succeeded. |
| Embedding measurement | A 64-text direct encode took 2.174 s on CPU and 0.036 s on L4 GPU after model load; this is a container microbenchmark, not an end-to-end local comparison. |
| Data-plane safety | A fresh disposable collection reached `manifest_revision: 0` and no Qdrant collection was created; no R2 graph object was written. |

## Constraints discovered

1. `embedding/runtime_resolver.py` accepts only `auto`, `cpu`, and `mps` and
   resolves Linux `auto` to CPU. It must explicitly support CUDA before the
   existing Ingest runner can use the validated GPU.
2. The locked image does not install spaCy model `en_core_web_sm`; the optional
   persistent graph stage will fail until the Modal image includes it.
3. A previously populated collection rejected manifest access with a backend
   namespace mismatch. This is correct ADR 0002 fail-closed behavior: never
   repair or overwrite that manifest implicitly. Validation used a new
   disposable collection instead.
4. The required controlled `replace-document` retry was intentionally not run:
   running it safely requires the implementation changes above and must prove
   claim, fence, generation, manifest, artifact, and stale-point behavior.

## Cleanup and handoff

The temporary Modal Secret and Volume used by this validation were deleted.
The validation created no Qdrant points/collection and no R2 graph artifact.

[Implement: GPU-capable Modal Ingest Run](https://github.com/amaldevice/graph-rag-summarizer/issues/98)
owns the controlled retry, CUDA resolver support, spaCy image dependency,
durable output policy, and the first `modal run` Ingest implementation.
