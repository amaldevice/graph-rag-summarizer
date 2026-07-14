# PR B — bounded global relation recovery

**Issues:** #45, #46, #47, #48  
**Branch:** `feat/global-relation-recovery`  
**Depends on:** merged PR A / ADR 0002; policy authority: ADR 0003.

## Scope

1. Normalize local relation evidence and distinguish weak from active edges.
2. Canonicalize conservative entity variants and classify weak/orphan/query-protected evidence.
3. Recover only bounded cross-chunk candidates from semantic and hierarchy neighborhoods.
4. Verify candidates through the existing sequential provider fallback; retain unavailable/rejected evidence only as diagnostics.

## Exclusions

No adaptive topology/community selection (#49–#51), context allocation (#52), all-pairs search, mandatory provider calls, or launcher changes.

## Public test seams

- Graph artifact construction and diagnostics from an Ingest Run.
- Persistent graph artifact load/query compatibility behavior.
- Deterministic unit fixtures for candidate caps and provider-unavailable verification.
