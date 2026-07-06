# Issue slices — Qdrant-safe batched Ingest Runs

Parent PRD: #33 — https://github.com/amaldevice/graph-rag-summarizer/issues/33

## Published vertical slices

1. **#34 — Ship Qdrant-safe batched uploads for large Ingest Runs**
   - URL: https://github.com/amaldevice/graph-rag-summarizer/issues/34
   - Blocked by: None - can start immediately
   - User stories covered: 1-15
   - Scope: Keep the same Ingest Run flow, but split Qdrant point uploads into bounded batches at the vector store write boundary so large hierarchy-aware chunk sets do not exceed Qdrant Cloud request-size limits.

## Testing seam

Use the existing vector store upload seam with a fake Qdrant client. Add one focused regression proving large fake chunk sets produce multiple upsert calls while preserving payload metadata. Keep existing Ingest Run launcher tests passing.
