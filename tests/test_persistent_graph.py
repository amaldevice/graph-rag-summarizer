import gzip
import hashlib
import json
import os
import socket

import networkx as nx
import pytest

from graph.persistent import (
    GraphArtifactStore,
    InMemoryObjectStore,
    ManifestStore,
    canonical_json_bytes,
    deserialize_graph,
    serialize_graph,
    source_fingerprint,
    PersistentGraphPipeline,
    PersistentGraphReader,
    backfill_qdrant_collection,
)


def _chunks():
    return [
        {
            "chunk_id": 1,
            "chunk_uid": "paper:chunk:1",
            "text": "Alpha supports Beta.",
            "level": "paragraph",
            "hierarchy": {"section": "Findings"},
            "layout": {"kind": "text"},
            "page_no": 2,
        },
        {
            "chunk_id": 0,
            "chunk_uid": "paper:chunk:0",
            "text": "Alpha is introduced.",
            "level": "paragraph",
            "hierarchy": {"section": "Introduction"},
            "layout": {"kind": "text"},
            "page_no": 1,
        },
    ]


def test_canonical_graph_bytes_and_source_fingerprint_are_stable():
    graph = nx.Graph()
    graph.add_node("chunk_0", type="chunk", chunk_uid="paper:chunk:0")
    graph.add_node("ent_alpha", type="entity", canonical_id="alpha")
    graph.add_edge("chunk_0", "ent_alpha", weight=1.0, edge_type="mentions")

    first = serialize_graph(graph, _chunks(), document_id="paper", generation=1, raw_evidence=[])
    second = serialize_graph(graph, list(reversed(_chunks())), document_id="paper", generation=1, raw_evidence=[])
    assert first == second
    assert canonical_json_bytes(json.loads(first)) == first
    assert source_fingerprint(_chunks(), "paper") == source_fingerprint(list(reversed(_chunks())), "paper")
    assert gzip.decompress(gzip.compress(first)) == first
    assert deserialize_graph(first)["document_id"] == "paper"


def test_canonical_json_normalizes_ecmascript_number_ranges():
    assert canonical_json_bytes({"small": 1e-6, "large": 1e20, "huge": 1e21, "whole": 1.0}) == (
        b'{"huge":1e+21,"large":100000000000000000000,"small":0.000001,"whole":1}'
    )


def test_artifact_retry_accepts_a_cloud_conditional_conflict_when_bytes_match():
    class ConditionalConflict(Exception):
        response = {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}}

    class ConflictStore(InMemoryObjectStore):
        def put(self, key, data, **kwargs):
            if kwargs.get("if_none_match") and key in self.objects:
                raise ConditionalConflict()
            return super().put(key, data, **kwargs)

        @staticmethod
        def is_conditional_conflict(exc):
            return isinstance(exc, ConditionalConflict)

    objects = ConflictStore()
    artifacts = GraphArtifactStore(objects, collection="papers")
    claim = {
        "document_id": "../paper/a",
        "pending_version": 1,
        "document_generation": 1,
        "source_fingerprint": "fingerprint",
        "operation_id": "op",
        "pending_attempt_id": "attempt",
        "build_attempt_id": "build",
        "pending_backend": {"kind": "memory", "namespace": "test"},
    }
    first = artifacts.write(claim, b'{"document_id":"paper"}')
    assert artifacts.write(claim, b'{"document_id":"paper"}') == first
    assert artifacts.key("../paper/a", 1) == "graphs/papers/..%2Fpaper%2Fa/v1/graph.json.gz"


def test_manifest_reserves_versions_and_publishes_only_validated_artifact():
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers", backend={"kind": "memory", "namespace": "test"})
    artifacts = GraphArtifactStore(objects, collection="papers")

    claim = manifests.reserve("paper", "op-1", "fingerprint-1", mode="append")
    assert claim["pending_version"] == 1
    key, digest = artifacts.write(claim, b'{"document_id":"paper"}')
    manifests.bind_artifact(claim, key, digest)
    assert manifests.get("paper")["version_ledger"][0]["artifact_digest"] == digest
    published = manifests.publish(claim, key, digest)
    assert published["status"] == "available"
    assert published["active_version"] == 1

    replacement = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")
    assert replacement["pending_version"] == 2
    assert manifests.get("paper")["status"] == "pending"
    manifests.bind_artifact(replacement, "graphs/papers/paper/v2/graph.json.gz", "digest-2")
    assert manifests.publish(replacement, "graphs/papers/paper/v2/graph.json.gz", "digest-2")["active_version"] == 2
    assert manifests.get("paper")["previous_pointer"]["version"] == 1


def test_missing_manifest_and_corrupt_artifact_use_safe_states():
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers")
    assert manifests.get("missing") is None
    claim = manifests.reserve("paper", "op-1", "fingerprint", mode="append")
    failed = manifests.fail(claim, "artifact validation failed")
    assert failed["status"] == "unavailable"
    assert failed["active_artifact_key"] is None


def test_manifest_snapshot_hashes_exact_stored_bytes():
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers", backend={"kind": "memory", "namespace": ""})
    raw = b'{"collection":"papers", "documents":{}, "manifest_backend":{"kind":"memory","namespace":""}, "manifest_revision":0}'
    objects.put("graphs/papers/manifest.json", raw, if_none_match=True)

    snapshot = manifests.read_snapshot()

    assert snapshot.data == raw
    assert snapshot.digest == hashlib.sha256(raw).hexdigest()


def test_manifest_full_snapshot_cas_rejects_stale_writer():
    objects = InMemoryObjectStore()
    first = ManifestStore(objects, collection="papers")
    second = ManifestStore(objects, collection="papers")
    snapshot = first.read_snapshot()

    candidate = dict(snapshot.manifest)
    candidate["collection_attempt_id"] = "writer-a"
    first._write(candidate, snapshot)

    stale_candidate = dict(snapshot.manifest)
    stale_candidate["collection_attempt_id"] = "writer-b"
    with pytest.raises(RuntimeError, match="snapshot changed"):
        second._write(stale_candidate, snapshot)


def test_reserve_same_operation_resumes_exact_claim():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")
    resumed = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")

    assert resumed["pending_version"] == first["pending_version"]
    assert resumed["pending_attempt_id"] == first["pending_attempt_id"]
    assert resumed["build_attempt_id"] == first["build_attempt_id"]


def test_append_resumes_same_pending_claim_before_duplicate_append_rejection():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint", mode="append")

    resumed = manifests.reserve("paper", "op-1", "fingerprint", mode="append")

    assert resumed["pending_version"] == first["pending_version"]
    assert resumed["pending_attempt_id"] == first["pending_attempt_id"]


def test_pipeline_reserve_reuses_persisted_pending_operation_for_resume():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    pipeline = PersistentGraphPipeline("papers", manifests=manifests, artifacts=GraphArtifactStore(InMemoryObjectStore(), "papers"))
    chunks = _chunks()

    first = pipeline.reserve(chunks, "paper", mode="replace-document")
    resumed = pipeline.reserve(chunks, "paper", mode="replace-document")

    assert resumed["operation_id"] == first["operation_id"]
    assert resumed["pending_attempt_id"] == first["pending_attempt_id"]


def test_manifest_lease_blocks_claim_changes_until_qdrant_mutation_finishes():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")

    def competing_manifest_write():
        manifests.reserve("other", "op-2", "fingerprint-2")

    with pytest.raises(RuntimeError, match="Qdrant mutation is already fenced"):
        manifests.mutate_claim(claim, competing_manifest_write)

    assert manifests.read_snapshot().manifest["active_mutation_id"] is None
    assert manifests.get("other") is None


def test_manifest_lease_can_be_taken_over_only_for_an_expired_matching_claim():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")
    snapshot = manifests.read_snapshot()
    manifest = snapshot.manifest
    manifest.update({
        "active_mutation_id": "crashed-owner",
        "active_mutation_scope": "document",
        "active_mutation_operation_id": claim["operation_id"],
        "active_mutation_document_id": claim["document_id"],
        "active_mutation_attempt_id": claim["pending_attempt_id"],
        "active_mutation_started_at": "2000-01-01T00:00:00+00:00",
        "active_mutation_pid": os.getpid() + 1000000,
        "active_mutation_host": socket.gethostname(),
    })
    manifests._write(manifest, snapshot)

    assert manifests.mutate_claim(claim, lambda: "resumed") == "resumed"
    assert manifests.read_snapshot().manifest["active_mutation_id"] is None


def test_reserve_rebuilds_next_version_from_ledger_when_counter_is_stale():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint-1")
    manifests.bind_artifact(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    manifests.publish(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    snapshot = manifests.read_snapshot()
    manifest = snapshot.manifest
    manifest["documents"]["paper"]["next_version"] = 1
    manifests._write(manifest, snapshot)

    replacement = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")

    assert replacement["pending_version"] == 2
    assert first["version_ledger"][0]["version"] == 1


def test_backfill_rejects_incomplete_vector_metadata_without_reembedding():
    class LegacyQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert document_id is None
            assert include_vectors is True
            return [{
                "document_id": "paper",
                "chunk_id": 1,
                "text": "legacy",
                "_embedding": [0.1, 0.2],
                "document_generation": 1,
            }]

    result = backfill_qdrant_collection(LegacyQdrant(), "papers")

    assert result == [{
        "status": "unavailable",
        "document_id": "paper",
        "failure_reason": "chunk identity metadata is incomplete; rebuild required",
    }]


def test_collection_fence_invalidates_retained_document_claims():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")
    manifests.tombstone_documents({"paper"}, "replace-collection:unique")

    with pytest.raises(RuntimeError, match="stale graph claim"):
        manifests.assert_claim_current(claim)


def test_tombstone_proof_burns_versions_and_commits_control_digest():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint-1")
    manifests.bind_artifact(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    manifests.publish(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    pending = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")
    tombstone = manifests.tombstone_documents(set(), "replace-1")

    states = {item["version"]: item["state"] for item in tombstone["documents"]["paper"]["version_ledger"]}
    assert states == {1: "tombstoned", 2: "burned"}
    assert tombstone["documents"]["paper"]["active_version"] is None
    assert tombstone["documents"]["paper"]["pending_version"] is None
    controls = manifests.tombstone_controls(tombstone)
    committed = manifests.commit_tombstone_proof(controls)

    assert committed["pending_tombstone_set_digest"] is None
    assert committed["tombstone_set_digest"] == hashlib.sha256(canonical_json_bytes(controls)).hexdigest()
    assert pending["pending_version"] == 2


def test_tombstone_proof_rejects_modified_payload():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint")
    manifests.bind_artifact(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    manifests.publish(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    tombstone = manifests.tombstone_documents(set(), "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    controls[0]["payload"]["tombstone_operation_id"] = "wrong"

    with pytest.raises(RuntimeError, match="tombstone proof"):
        manifests.commit_tombstone_proof(controls)


def test_tombstoned_document_reintroduction_stages_deny_cleanup():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint")
    manifests.bind_artifact(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    manifests.publish(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    tombstone = manifests.tombstone_documents(set(), "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    manifests.commit_tombstone_proof(controls)
    manifests.release_collection_fence("replace-1", tombstone["collection_fence_token"])

    reintroduction = manifests.tombstone_documents({"paper"}, "replace-2")
    assert reintroduction["documents"]["paper"]["status"] == "pending"
    assert reintroduction["pending_tombstone_cleanup_ids"] == [controls[0]["point_id"]]
    assert manifests.tombstone_controls(reintroduction) == []
    fresh_claim = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-collection")
    assert fresh_claim["document_generation"] == 2
    committed = manifests.commit_tombstone_proof([])
    assert committed["pending_tombstone_set_digest"] == "pending"
    finalized = manifests.finalize_tombstone_cleanup("replace-2", reintroduction["collection_fence_token"])
    assert finalized["pending_tombstone_set_digest"] is None
    assert finalized["tombstone_set_digest"] == manifests.tombstone_proof_digest(finalized)


def test_reintroduction_publish_commits_tombstone_set_with_active_pointer():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint-1")
    manifests.bind_artifact(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    manifests.publish(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    tombstone = manifests.tombstone_documents(set(), "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    manifests.commit_tombstone_proof(controls)
    manifests.release_collection_fence("replace-1", tombstone["collection_fence_token"])
    reintroduction = manifests.tombstone_documents({"paper"}, "replace-2")
    claim = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-collection")
    key = "graphs/papers/paper/v2/graph.json.gz"
    manifests.bind_artifact(claim, key, "digest-2")

    published = manifests.publish(claim, key, "digest-2")

    assert published["status"] == "available"
    assert manifests.read_snapshot().manifest["pending_tombstone_set_digest"] is None
    assert manifests.read_snapshot().manifest["pending_tombstone_cleanup_ids"] == []
    assert reintroduction["collection_fence_token"] == published["collection_fence_token"]


def test_artifact_read_rejects_noncanonical_json_body():
    objects = InMemoryObjectStore()
    artifacts = GraphArtifactStore(objects, collection="papers")
    claim = {
        "document_id": "paper",
        "pending_version": 1,
        "document_generation": 1,
        "source_fingerprint": "fingerprint",
        "operation_id": "op",
        "pending_attempt_id": "attempt",
        "build_attempt_id": "build",
        "pending_backend": {"kind": "memory", "namespace": "test"},
    }
    key, digest = artifacts.write(claim, b'{"b":1,"a":2}')

    with pytest.raises(ValueError, match="canonical"):
        artifacts.read(key, digest)


def test_pipeline_publishes_graph_and_reader_returns_temporary_view():
    class Extractor:
        def extract_entities(self, chunks):
            return {chunk["chunk_uid"]: [(chunk["text"], "ORG")] for chunk in chunks}, [
                {"chunk_uid": chunk["chunk_uid"], "chunk_id": chunk["chunk_id"], "text": chunk["text"], "label": "ORG"}
                for chunk in chunks
            ]

        def extract_relations_llm(self, text, entities):
            del text, entities
            return []

    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers", backend={"kind": "memory", "namespace": "test"})
    artifacts = GraphArtifactStore(objects, collection="papers")
    pipeline = PersistentGraphPipeline("papers", manifests=manifests, artifacts=artifacts)
    result = pipeline.build_and_publish(
        _chunks(), [[1.0, 0.0], [0.9, 0.1]], "paper",
        entity_extractor=Extractor(),
    )
    assert result["status"] == "available"
    graph = PersistentGraphReader(manifests, artifacts).load("paper", [_chunks()[1]])
    assert graph is not None
    assert "chunk_0" in graph


def test_replace_collection_tombstones_omitted_documents():
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers")
    claim = manifests.reserve("paper-a", "op-a", "fp-a")
    manifests.bind_artifact(claim, "graphs/papers/paper-a/v1/graph.json.gz", "a")
    manifests.publish(claim, "graphs/papers/paper-a/v1/graph.json.gz", "a")
    manifests.tombstone_documents({"paper-b"}, "replace-1")
    assert manifests.get("paper-a")["status"] == "tombstoned"
    assert manifests.preflight("paper-a")["allowed"] is False
