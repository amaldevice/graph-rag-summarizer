# Recover bounded cross-chunk relations from document graph evidence

**Status:** Accepted  
**Date:** 2026-07-12

## Context

Local extraction can identify entities and relations inside one chunk, but it can miss supported relationships whose evidence is distributed across a document. Treating every same-chunk entity pair as an equally strong relation also creates noisy cliques. A full all-pairs search would make ingest cost and optional LLM verification unbounded.

## Decision

Recover cross-chunk relations with a bounded, document-scoped candidate policy:

1. Start from weak or orphan graph regions.
2. Inspect only bounded semantic-neighbor and hierarchy/section neighborhoods.
3. Generate entity-pair candidates inside those neighborhoods, never across every entity pair in the document.
4. Apply stable per-region and per-document candidate caps. These are operational defaults, not truth thresholds, and are tuned with deterministic fixtures and smoke evidence.
5. Verify candidates with a bounded evidence window containing candidate entities, supporting chunks, semantic neighbors, hierarchy metadata, and existing raw evidence.
6. Use the existing shared provider router and sequential fallback chain. Stop at the first valid structured result; unavailable providers leave the candidate unverified instead of failing ingest.
7. Represent accepted cross-chunk relations as direct entity-to-entity edges with relation type, source, confidence, status, and supporting chunk IDs.
8. Keep raw evidence for weak, rejected, and unverified candidates. Only explicit or verified relations become active relation edges.
9. Exclude orphan/low-support entity nodes from active topology while retaining their diagnostics. Retrieved chunk nodes remain eligible for query protection.

## Alternatives rejected

- **All-pairs entity comparison:** unbounded cost and high noise for large documents.
- **Send the full document to every verifier:** unnecessary prompt size and weaker evidence locality.
- **Call every LLM provider for consensus:** multiplies cost and latency; the existing sequential fallback chain is sufficient for the first version.
- **Delete weak evidence immediately:** removes the audit trail and prevents later recovery or policy tuning.
- **Make LLM verification mandatory:** makes graph ingest fragile when providers are unavailable.

## Consequences

Positive:

- Supported cross-chunk relations can be recovered before any query exists.
- Weak co-occurrence no longer dominates the active graph.
- Every accepted or rejected decision can be traced to bounded evidence and source chunks.
- Ingest cost and LLM usage remain bounded and configurable.

Costs and constraints:

- Candidate generation and verification add work to Ingest Runs.
- Candidate caps and evidence policies need tuning against representative documents.
- Unverified candidates remain available for diagnostics but cannot be treated as confirmed graph facts.
- Later adaptive topology and community selection must consume the active graph and preserve the raw evidence contract.

## Related work

- Issue #39 — hybrid entity/relation extraction availability.
- Issues #45–#48 — relation evidence, canonicalization, candidate generation, and verification/recovery.
- Issue #44 — adaptive global graph construction parent PRD.
- Wayfinder ticket #59 — bounded global relation recovery from weak graph regions.
