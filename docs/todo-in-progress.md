# Todo / In Progress

## Planned / Backlog
- PR B — bounded global relation recovery (`feat/global-relation-recovery`)
- PR C — adaptive topology and stable community selection (`feat/adaptive-topology-community`) [PARTIALLY IN PROGRESS]
- PR D — query-time adaptive context allocation (`feat/adaptive-context-allocation`)

## In Progress
- Execute `docs/handoff-2026-07-13-persistent-graph-implementation.md` end to end:
  - [x] **Phase 0 — land the decisions** (Merged PR #62, #63, #64, #65, #66)
  - [ ] **PR A — persistent ingest graph foundation** (In Progress — implementing review blockers before merge)
  - [ ] **PR C — adaptive topology and stable community selection (Issue #49)** (In Progress — running in parallel via git worktree)

### PR A review blockers
- Durable cross-process manifest/Qdrant fencing and full-snapshot CAS.
- Qdrant deny-control enumeration, proof digest validation, and ordered fail-closed preflight.
- Server-side active generation/attempt filters for vector and graph planes.
- Tombstone/version-ledger resume and replacement lifecycle completion.

### PR C (Issue #49) active tasks
- Implement adaptive mutual-kNN semantic chunk topology with bounded degree.
- Verify using synthetic sparse, dense, and degenerate fixtures.

