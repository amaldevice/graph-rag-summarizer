# Research: local-controller and Modal-worker boundary

**Status:** resolved
**Tracker:** [Research: define local-controller and Modal-worker boundary](https://github.com/amaldevice/graph-rag-summarizer/issues/94)

## Decision

`main.py` remains the human-facing local controller. It parses CLI input,
executes the interactive wizard, applies Launch Profile overrides, and normally
dispatches runner functions. A Modal local entrypoint should instead build the
same non-interactive config and call a remote Function that invokes
`launcher.runners` directly. Do not run the wizard or pass `/Users/...` paths
inside Modal.

`profile` remains an infrastructure pairing: `local` maps to local Qdrant and
MinIO; `cloud` maps to Qdrant Cloud and R2 (`main.py:27-35`). Compute placement
is a separate backend choice.

## Minimum request and result

```text
all:        mode, profile, collection, collection_mode, verbose
query/full: query, retrieval_limit
ingest:     remote PDF key or bytes -> worker-local pdf_path,
            ingest_mode, document_id, collection_operation_id?
outputs:    json_output?, artifact_dir?, enable_graph_artifact?
```

The worker first applies the existing profile mapping, then builds the current
runner config. It returns a serializable completion envelope containing mode,
collection, optional document ID, status, and durable artifact locations.
Runner functions currently return `None`, so a container-local path is never a
valid result.

## Runner evidence

| Runner | Inputs and effect | Durable result |
| --- | --- | --- |
| Query-Only (`launcher/runners.py:632-702`) | Embeds a query, configures document-safe authorization when applicable, and reads Qdrant. | Optional JSON artifact. |
| Ingest (`launcher/runners.py:705-1013`) | Reads the PDF through Docling, embeds chunks, mutates Qdrant, and optionally builds the persistent graph. | Qdrant data; object-store graph; local graph-status file unless a durable output mount is supplied. |
| Full-Pipeline (`launcher/runners.py:1016-1459`) | Embeds/retrieves, reuses or builds a graph, calls LLM providers, evaluates/retries. | JSON/CSV/TXT output beneath `artifact_dir`. |

## Non-negotiable persistence rules

- Preserve ADR 0001: Launch Profile selects the Qdrant/object-storage pair,
  not Modal compute.
- Preserve ADR 0002: existing `PersistentGraphPipeline` owns reservation,
  generation, attempt, fence, and publication. The remote worker calls it; it
  must not reimplement its lifecycle.
- R2 remains the authoritative store for
  `graphs/{collection}/{document_id}/v{version}/graph.json.gz` and its manifest.
  Modal Volume may hold cache and ordinary outputs only.
- A remote run must use Qdrant Cloud/R2 or deliberately exposed secure endpoints;
  local Qdrant and `localhost:9000` MinIO cannot be assumed reachable.

## Portability blockers before implementation

1. `embedding/runtime_resolver.py:53-57,190-211` rejects `cuda` and resolves
   Linux `auto` to CPU; ONNX is CPU-only (`148-167`).
2. `TextEmbedder` loads SentenceTransformer in the executing process
   (`embedding/embedder.py:24-84`); its writable project-relative cache needs a
   Modal image or Volume policy (`embedding/cache_paths.py:6-28`).
3. Docling and image export require worker-local paths
   (`preprocessing/docling_loader.py:24-30`; `preprocessing/image_exporter.py:21-24,61-106`).
4. Query JSON and Full-Pipeline reports are ordinary filesystem writes, so their
   destinations need a durable mount or upload before return.
5. The worker needs Modal Secret-injected Qdrant, R2, and LLM provider
   credentials; it must not copy `.env` into the Image.

## Architecture references

- `main.py:27-102`
- `launcher/contract.py:541-596`
- `graph/persistent.py:347-428,441-586,898-1030,1279-1318,1459-1468`
- `docs/adr/0001-profile-driven-single-launcher.md`
- `docs/adr/0002-persistent-document-graph-at-ingest.md`
