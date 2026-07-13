# Todo / In Progress

## Planned / Backlog
- PR B — bounded global relation recovery (`feat/global-relation-recovery`)
- PR C — adaptive topology and stable community selection (`feat/adaptive-topology-community`)
- PR D — query-time adaptive context allocation (`feat/adaptive-context-allocation`)

## In Progress
- Execute `docs/handoff-2026-07-13-persistent-graph-implementation.md` end to end:
  - [x] **Phase 0 — land the decisions** (Merged PR #62, #63, #64, #65, #66)
  - [ ] **PR A — persistent ingest graph foundation** (In Progress — safety-only branch; implementation and verification)

### PR A review blockers
- Durable cross-process manifest/Qdrant fencing and full-snapshot CAS.
- Qdrant deny-control enumeration, proof digest validation, and ordered fail-closed preflight.
- Server-side active generation/attempt filters for vector and graph planes.
- Tombstone/version-ledger resume and replacement lifecycle completion.
