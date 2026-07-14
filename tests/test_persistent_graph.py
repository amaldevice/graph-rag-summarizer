import gzip
import hashlib
import json
import os
import socket

import networkx as nx
import pytest

import graph.persistent as persistent
from graph.persistent import (
    GraphArtifactStore,
    GraphArtifactCorruptionError,
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


def test_document_graph_persists_weak_evidence_without_activating_its_edge():
    class Extractor:
        relation_extraction_mode = "spacy-only"

        def extract_entities(self, chunks):
            del chunks
            return {
                "paper:chunk:0": [
                    {"text": "Acme, Inc."},
                    {"text": "Gamma"},
                ],
                "paper:chunk:1": [
                    {"text": "  acme inc  "},
                    {"text": "Beta"},
                ],
            }, [
                {"chunk_uid": "paper:chunk:0", "text": "Acme, Inc.", "label": "ORG"},
                {"chunk_uid": "paper:chunk:0", "text": "Gamma", "label": "ORG"},
                {"chunk_uid": "paper:chunk:1", "text": "  acme inc  ", "label": "ORG"},
                {"chunk_uid": "paper:chunk:1", "text": "Beta", "label": "ORG"},
            ]

        def extract_relations_llm(self, text, entities):
            del entities
            if text == "weak":
                return [{
                    "head": "Acme, Inc.",
                    "relation": "co-occurs_with",
                    "tail": "Gamma",
                    "source": "rule-based",
                }]
            return [{
                "head": "acme inc",
                "relation": "supports",
                "tail": "Beta",
            }]

    class Detector:
        def detect(self, graph):
            return graph, [], {}, 0.0

    graph, details = persistent.build_document_graph(
        [
            {"chunk_id": 0, "chunk_uid": "paper:chunk:0", "text": "weak"},
            {"chunk_id": 1, "chunk_uid": "paper:chunk:1", "text": "explicit"},
        ],
        [[1.0, 0.0], [0.0, 1.0]],
        "paper",
        entity_extractor=Extractor(),
        detector=Detector(),
    )

    weak = next(item for item in details["raw_evidence"] if item["source"] == "rule-based")
    explicit = next(item for item in details["raw_evidence"] if item["relation"] == "supports")

    assert weak["support_chunk_uids"] == ["paper:chunk:0"]
    assert weak["evidence_type"] == "same_chunk"
    assert weak["status"] == "unverified"
    assert weak not in details["active_evidence"]
    assert not graph.has_edge("ent_acme_inc", "ent_gamma")

    assert details["active_evidence"] == [explicit]
    assert explicit["support_chunk_uids"] == ["paper:chunk:1"]
    assert explicit["evidence_type"] == "explicit"
    assert explicit["resolved_weight"] == 1.0
    assert graph["ent_acme_inc"]["ent_beta"] == {
        "relation": "supports",
        "source": "llm",
        "scope": "local",
        "confidence": 1.0,
        "support_chunk_uids": ["paper:chunk:1"],
        "evidence_type": "explicit",
        "verification_state": "accepted",
        "status": "accepted",
        "resolved_weight": 1.0,
        "weight": 1.0,
        "relation_evidence": [explicit],
        "evidence_count": 1,
        "edge_type": "entity_relation",
    }
    diagnostics = details["diagnostics"]
    assert diagnostics["raw_evidence_count"] == 2
    assert diagnostics["active_evidence_count"] == 1
    assert any(
        item["canonical_id"] == "ent_acme_inc"
        and item["aliases"] == ["  acme inc  ", "Acme, Inc."]
        for item in diagnostics["canonicalization"]["canonical_entities"]
    )
    assert diagnostics["entity_support"]["strongly_supported"] == ["ent_acme_inc", "ent_beta"]
    assert diagnostics["entity_support"]["weakly_supported"] == ["ent_gamma"]


def test_graph_builder_normalizes_legacy_explicit_relations_before_edge_gating():
    from graph.graph_builder import GraphBuilder

    graph = GraphBuilder(knn_k=1, sim_threshold=1.0).build_graph(
        chunks=[{"chunk_id": 0, "text": "entities"}],
        chunk_embeddings=[[1.0, 0.0]],
        all_entities=[
            {"chunk_id": 0, "text": "Alpha", "label": "ORG"},
            {"chunk_id": 0, "text": "Beta", "label": "ORG"},
            {"chunk_id": 0, "text": "Gamma", "label": "ORG"},
        ],
        all_relations=[
            {"head": "Alpha", "relation": "supports", "tail": "Beta"},
            {
                "head": "Alpha",
                "relation": "co-occurs_with",
                "tail": "Gamma",
                "source": "rule-based",
            },
        ],
    )

    assert graph["ent_alpha"]["ent_beta"]["edge_type"] == "entity_relation"
    assert graph["ent_alpha"]["ent_beta"]["resolved_weight"] == 1.0
    assert not graph.has_edge("ent_alpha", "ent_gamma")


def test_graph_builder_coalesces_active_pair_evidence_deterministically():
    from graph.graph_builder import GraphBuilder

    kwargs = {
        "chunks": [{"chunk_id": 0, "text": "entities"}],
        "chunk_embeddings": [[1.0, 0.0]],
        "all_entities": [
            {"chunk_id": 0, "text": "Alpha", "label": "ORG"},
            {"chunk_id": 0, "text": "Beta", "label": "ORG"},
        ],
    }
    evidence = [
        {
            "head": "Alpha",
            "relation": "supports",
            "tail": "Beta",
            "source": "provider",
            "support_chunk_uids": ["paper:chunk:2"],
        },
        {
            "head": "Beta",
            "relation": "confirms",
            "tail": "Alpha",
            "support_chunk_uids": ["paper:chunk:1"],
            "evidence_type": "verified",
        },
    ]

    first = GraphBuilder(knn_k=1, sim_threshold=1.0).build_graph(
        **kwargs,
        all_relations=evidence,
    )
    second = GraphBuilder(knn_k=1, sim_threshold=1.0).build_graph(
        **kwargs,
        all_relations=list(reversed(evidence)),
    )

    first_edge = first["ent_alpha"]["ent_beta"]
    assert first_edge == second["ent_alpha"]["ent_beta"]
    assert first_edge["evidence_count"] == 2
    assert first_edge["support_chunk_uids"] == ["paper:chunk:1", "paper:chunk:2"]
    assert {
        (item["head"], item["relation"], item["tail"])
        for item in first_edge["relation_evidence"]
    } == {
        ("Alpha", "supports", "Beta"),
        ("Beta", "confirms", "Alpha"),
    }


def test_canonical_graph_bytes_sort_relation_evidence():
    graph = nx.Graph()
    graph.add_node("chunk_0", type="chunk", chunk_uid="paper:chunk:0")
    evidence = [
        {"head": "Beta", "tail": "Gamma", "status": "accepted"},
        {"head": "Alpha", "tail": "Beta", "status": "unverified"},
    ]

    first = serialize_graph(graph, _chunks(), "paper", 1, evidence, {}, evidence[:1])
    second = serialize_graph(graph, _chunks(), "paper", 1, list(reversed(evidence)), {}, evidence[:1])

    assert first == second


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


def test_new_replace_operation_burns_an_incompatible_pending_reservation():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint-1", mode="replace-document")

    replacement = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")

    states = {
        item["operation_id"]: item["state"]
        for item in replacement["version_ledger"]
    }
    assert states["op-1"] == "burned"
    assert states["op-2"] == "reserved"
    assert replacement["pending_operation_id"] == "op-2"
    assert replacement["pending_version"] != first["pending_version"]


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


def _backfill_chunk(document_id="paper", chunk_id=1, generation=1, vector=None):
    return {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_uid": f"{document_id}:chunk:{chunk_id}",
        "text": f"chunk {chunk_id}",
        "document_generation": generation,
        "vector_point": True,
        "_embedding": [0.1, 0.2] if vector is None else vector,
    }


def test_backfill_converts_legacy_qdrant_scan_error_without_initializing_pipeline(monkeypatch):
    class LegacyQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert document_id is None
            assert include_vectors is True
            raise ValueError("legacy point without document_id cannot be backfilled")

    def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("pipeline must not initialize for a legacy scan error")

    monkeypatch.setattr(persistent, "PersistentGraphPipeline", unexpected_pipeline)

    assert backfill_qdrant_collection(LegacyQdrant(), "papers") == [{
        "status": "unavailable",
        "document_id": None,
        "failure_reason": "legacy Qdrant payload cannot be backfilled; rebuild required",
    }]


def test_backfill_rejects_non_mapping_payload_without_initializing_pipeline(monkeypatch):
    class MalformedQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            return ["not a Qdrant payload"]

    def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("pipeline must not initialize for a malformed payload")

    monkeypatch.setattr(persistent, "PersistentGraphPipeline", unexpected_pipeline)

    assert backfill_qdrant_collection(MalformedQdrant(), "papers") == [{
        "status": "unavailable",
        "document_id": None,
        "failure_reason": "Qdrant payload is malformed; rebuild required",
    }]


@pytest.mark.parametrize("generations", [(False,), (0,), (-1,), (1.5,), (1, 2)])
def test_backfill_rejects_invalid_or_inconsistent_document_generation_without_initializing_pipeline(
    monkeypatch,
    generations,
):
    class InvalidGenerationQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            return [
                _backfill_chunk(chunk_id=index, generation=generation)
                for index, generation in enumerate(generations)
            ]

    def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("pipeline must not initialize for invalid document generations")

    monkeypatch.setattr(persistent, "PersistentGraphPipeline", unexpected_pipeline)

    assert backfill_qdrant_collection(InvalidGenerationQdrant(), "papers") == [{
        "status": "unavailable",
        "document_id": "paper",
        "failure_reason": "document generation metadata is incomplete or inconsistent; rebuild required",
    }]


@pytest.mark.parametrize(
    "vectors",
    [([],), ([float("nan")],), ([True],), ([0.1, "invalid"],), ([0.1, 0.2], [0.3])],
)
def test_backfill_rejects_invalid_or_inconsistent_stored_vectors_without_initializing_pipeline(monkeypatch, vectors):
    class InvalidVectorQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            return [
                _backfill_chunk(chunk_id=index, vector=vector)
                for index, vector in enumerate(vectors)
            ]

    def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("pipeline must not initialize for invalid stored vectors")

    monkeypatch.setattr(persistent, "PersistentGraphPipeline", unexpected_pipeline)

    assert backfill_qdrant_collection(InvalidVectorQdrant(), "papers") == [{
        "status": "unavailable",
        "document_id": "paper",
        "failure_reason": "stored vectors are incomplete, invalid, or inconsistent; rebuild required",
    }]


def test_backfill_reuses_one_lazy_pipeline_and_passes_stored_vectors(monkeypatch):
    scanned_chunks = [
        _backfill_chunk(document_id="zeta", chunk_id=2, vector=[0.2, 0.3]),
        _backfill_chunk(document_id="alpha", chunk_id=1, vector=[0.4, 0.5]),
    ]

    class Qdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert document_id is None
            assert include_vectors is True
            return scanned_chunks

    class RecordingPipeline:
        instances = []

        def __init__(self, collection, object_store=None):
            self.collection = collection
            self.object_store = object_store
            self.calls = []
            self.instances.append(self)

        def backfill(self, chunks, vectors, document_id, **kwargs):
            self.calls.append((chunks, vectors, document_id, kwargs))
            return {"status": "available", "document_id": document_id}

    object_store = object()
    monkeypatch.setattr(persistent, "PersistentGraphPipeline", RecordingPipeline)

    result = backfill_qdrant_collection(Qdrant(), "papers", object_store=object_store)

    assert result == [
        {"status": "available", "document_id": "alpha"},
        {"status": "available", "document_id": "zeta"},
    ]
    assert len(RecordingPipeline.instances) == 1
    pipeline = RecordingPipeline.instances[0]
    assert pipeline.collection == "papers"
    assert pipeline.object_store is object_store
    assert [call[1] for call in pipeline.calls] == [[[0.4, 0.5]], [[0.2, 0.3]]]
    assert [call[2] for call in pipeline.calls] == ["alpha", "zeta"]
    assert all(call[3]["qdrant"].__class__.__name__ == "Qdrant" for call in pipeline.calls)
    assert all("_embedding" in chunk for chunk in scanned_chunks)


def test_backfill_publishes_the_stored_qdrant_generation_to_manifest_and_artifact(monkeypatch):
    class Qdrant:
        prepared_claims = []
        verification_claims = []

        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert include_vectors is True
            return [_backfill_chunk(generation=2)]

        def materialize_backfill_claim(self, manifests, claim):
            assert claim["document_id"] == "paper"
            assert claim["document_generation"] == 2
            manifests.mark_vectors_ready(claim)
            self.prepared_claims.append(claim)

        def verify_graph_claim_current(self, claim):
            assert claim["document_id"] == "paper"
            assert claim["document_generation"] == 2
            self.verification_claims.append(claim)

    def build_graph(chunks, embeddings, document_id, **kwargs):
        assert document_id == "paper"
        assert embeddings == [[0.1, 0.2]]
        assert kwargs == {}
        return nx.Graph(), {
            "raw_evidence": [],
            "active_evidence": [],
            "diagnostics": {},
        }

    objects = InMemoryObjectStore()
    monkeypatch.setattr(persistent, "build_document_graph", build_graph)

    qdrant = Qdrant()
    result = backfill_qdrant_collection(qdrant, "papers", object_store=objects)

    assert result[0]["status"] == "available"
    manifests = ManifestStore(
        objects,
        collection="papers",
        backend={"kind": "injected", "namespace": "papers"},
    )
    entry = manifests.get("paper")
    assert entry["document_generation"] == 2
    assert entry["pending_generation"] is None
    assert len(entry["version_ledger"]) == 1
    assert entry["version_ledger"][0]["document_generation"] == 2
    assert entry["version_ledger"][0]["state"] == "published_available"
    artifact = GraphArtifactStore(objects, "papers").read(
        entry["active_artifact_key"],
        entry["artifact_digest"],
        entry["backend"],
        2,
        entry["source_fingerprint"],
    )
    assert deserialize_graph(artifact)["document_generation"] == 2
    assert len(qdrant.prepared_claims) == 1
    assert len(qdrant.verification_claims) == 2


def test_backfill_refuses_to_publish_when_qdrant_revalidation_fails(monkeypatch):
    class Qdrant:
        def materialize_backfill_claim(self, manifests, claim):
            del manifests, claim
            raise RuntimeError("Qdrant generation changed")

        def verify_graph_claim_current(self, claim):
            del claim
            raise RuntimeError("Qdrant generation changed")

    def build_graph(chunks, embeddings, document_id, **kwargs):
        del chunks, embeddings, document_id, kwargs
        return nx.Graph(), {"raw_evidence": [], "active_evidence": [], "diagnostics": {}}

    objects = InMemoryObjectStore()
    pipeline = PersistentGraphPipeline("papers", object_store=objects)
    monkeypatch.setattr(persistent, "build_document_graph", build_graph)

    result = pipeline.backfill(
        [_backfill_chunk(generation=2)],
        [[0.1, 0.2]],
        "paper",
        document_generation=2,
        qdrant=Qdrant(),
    )

    assert result["status"] == "stale"
    assert "Qdrant generation changed" in result["failure_reason"]
    assert pipeline.manifests.get("paper")["status"] == "stale"


def test_backfill_rejects_conflicting_manifest_generation_without_advancing_it(monkeypatch):
    class Qdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            return [_backfill_chunk(generation=2)]

    objects = InMemoryObjectStore()
    manifests = ManifestStore(
        objects,
        collection="papers",
        backend={"kind": "injected", "namespace": "papers"},
    )
    original = manifests.reserve("paper", "existing-operation", "existing-fingerprint")

    def unexpected_build(*args, **kwargs):
        raise AssertionError("generation-conflicting backfill must not build an artifact")

    monkeypatch.setattr(persistent, "build_document_graph", unexpected_build)

    result = backfill_qdrant_collection(Qdrant(), "papers", object_store=objects)

    assert result == [{
        "status": "unavailable",
        "entry": original,
        "failure_reason": "manifest document generation conflicts with Qdrant; rebuild required",
    }]
    assert manifests.get("paper") == original


def test_backfill_rejects_boolean_chunk_id_without_initializing_pipeline(monkeypatch):
    class Qdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            return [_backfill_chunk(chunk_id=True)]

    def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("pipeline must not initialize for a boolean chunk id")

    monkeypatch.setattr(persistent, "PersistentGraphPipeline", unexpected_pipeline)

    assert backfill_qdrant_collection(Qdrant(), "papers") == [{
        "status": "unavailable",
        "document_id": "paper",
        "failure_reason": "chunk identity metadata is incomplete; rebuild required",
    }]


def test_backfill_rejects_durably_tombstoned_document_without_claim_publication(monkeypatch):
    class Qdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert document_id is None
            assert include_vectors is True
            return [_backfill_chunk(generation=1)]

    objects = InMemoryObjectStore()
    manifests = ManifestStore(
        objects,
        collection="papers",
        backend={"kind": "injected", "namespace": "papers"},
    )
    claim = manifests.reserve("paper", "ingest-operation", "source-fingerprint")
    manifests.bind_artifact(claim, "graphs/papers/paper/v1/graph.json.gz", "artifact-digest")
    manifests.publish(claim, "graphs/papers/paper/v1/graph.json.gz", "artifact-digest")
    tombstone = manifests.tombstone_documents({}, "replace-collection-operation")
    manifests.commit_tombstone_proof(manifests.tombstone_controls(tombstone))
    manifests.release_collection_fence(
        "replace-collection-operation",
        tombstone["collection_fence_token"],
    )
    tombstoned = manifests.get("paper")
    assert tombstoned["status"] == "tombstoned"

    def unexpected_build(*args, **kwargs):
        raise AssertionError("tombstoned backfill must not reserve or publish a graph artifact")

    monkeypatch.setattr(persistent.PersistentGraphPipeline, "build_and_publish", unexpected_build)

    result = backfill_qdrant_collection(Qdrant(), "papers", object_store=objects)

    assert result == [{
        "status": "unavailable",
        "entry": tombstoned,
        "failure_reason": "document is tombstoned; rebuild or re-ingest with replace-document required",
    }]
    assert manifests.get("paper") == tombstoned


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


def test_backfill_rejects_non_string_document_identity_even_when_qdrant_filter_cannot():
    class MalformedQdrant:
        def scroll_document_chunks(self, document_id=None, include_vectors=False):
            assert document_id is None
            assert include_vectors is True
            return [{
                "document_id": 42,
                "chunk_id": 1,
                "chunk_uid": "bad:chunk:1",
                "text": "malformed",
                "_embedding": [0.1, 0.2],
                "document_generation": 1,
                "vector_point": True,
            }]

    result = backfill_qdrant_collection(MalformedQdrant(), "papers")

    assert result[0]["status"] == "unavailable"
    assert "document identity" in result[0]["failure_reason"]


def test_collection_fence_invalidates_retained_document_claims():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint", mode="replace-document")
    manifests.tombstone_documents({"paper": "fingerprint"}, "replace-collection:unique")

    with pytest.raises(RuntimeError, match="stale graph claim"):
        manifests.assert_claim_current(claim)


@pytest.mark.parametrize("mode", ("append", "replace-document"))
def test_collection_fence_rejects_unrelated_document_reservations(mode):
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    manifests.tombstone_documents(
        {"replacement": source_fingerprint(_chunks(), "replacement")},
        "replace-collection:unique",
    )

    with pytest.raises(RuntimeError, match="collection replacement fence"):
        manifests.reserve("unrelated", f"{mode}-operation", "fingerprint", mode=mode)

    assert manifests.get("unrelated") is None


def test_collection_fence_allows_the_matching_replacement_reservation():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    pipeline = PersistentGraphPipeline(
        "papers",
        manifests=manifests,
        artifacts=GraphArtifactStore(InMemoryObjectStore(), "papers"),
    )
    fence = manifests.tombstone_documents(
        {"replacement": source_fingerprint(_chunks(), "replacement")},
        "replace-collection:unique",
    )

    claim = pipeline.reserve(_chunks(), "replacement", mode="replace-collection")

    assert claim["operation_id"] == fence["collection_operation_id"]
    assert claim["collection_fence_token"] == fence["collection_fence_token"]
    assert claim["collection_attempt_id"] == fence["collection_attempt_id"]


def test_collection_fence_binds_replacement_document_and_source_fingerprint():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    pipeline = PersistentGraphPipeline(
        "papers",
        manifests=manifests,
        artifacts=GraphArtifactStore(InMemoryObjectStore(), "papers"),
    )
    chunks = _chunks()
    fingerprint = source_fingerprint(chunks, "paper-a")
    fence = manifests.tombstone_documents({"paper-a": fingerprint}, "replace-collection:unique")

    claim = pipeline.reserve(chunks, "paper-a", mode="replace-collection")
    assert pipeline.reserve(chunks, "paper-a", mode="replace-collection") == claim

    changed_chunks = [dict(chunk) for chunk in chunks]
    changed_chunks[0]["text"] = "Changed source content."
    with pytest.raises(RuntimeError, match="collection replacement fence"):
        pipeline.reserve(changed_chunks, "paper-a", mode="replace-collection")
    with pytest.raises(RuntimeError, match="collection replacement fence"):
        pipeline.reserve(chunks, "paper-b", mode="replace-collection")
    with pytest.raises(RuntimeError, match="replacement target"):
        manifests.tombstone_documents(
            {"paper-a": source_fingerprint(changed_chunks, "paper-a")},
            fence["collection_operation_id"],
        )

    assert manifests.get("paper-b") is None
    assert manifests.read_snapshot().manifest["collection_retained_documents"] == {"paper-a": fingerprint}


def test_collection_fence_does_not_resume_a_stale_matching_operation_claim():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    stale = manifests.reserve(
        "replacement",
        "replace-collection:unique",
        "fingerprint",
        mode="replace-document",
    )
    fence = manifests.tombstone_documents({"replacement": "fingerprint"}, "replace-collection:unique")

    fresh = manifests.reserve(
        "replacement",
        "replace-collection:unique",
        "fingerprint",
        mode="replace-collection",
    )

    assert fresh["pending_attempt_id"] != stale["pending_attempt_id"]
    assert fresh["collection_fence_token"] == fence["collection_fence_token"]
    assert fresh["collection_attempt_id"] == fence["collection_attempt_id"]
    assert {item["state"] for item in fresh["version_ledger"]} == {"burned", "reserved"}
    with pytest.raises(RuntimeError, match="stale graph claim"):
        manifests.assert_claim_current(stale)


def test_tombstone_proof_burns_versions_and_commits_control_digest():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    first = manifests.reserve("paper", "op-1", "fingerprint-1")
    manifests.bind_artifact(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    manifests.publish(first, "graphs/papers/paper/v1/graph.json.gz", "digest-1")
    pending = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")
    tombstone = manifests.tombstone_documents({}, "replace-1")

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
    tombstone = manifests.tombstone_documents({}, "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    controls[0]["payload"]["tombstone_operation_id"] = "wrong"

    with pytest.raises(RuntimeError, match="tombstone proof"):
        manifests.commit_tombstone_proof(controls)


def test_tombstoned_document_reintroduction_stages_deny_cleanup():
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve("paper", "op-1", "fingerprint")
    manifests.bind_artifact(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    manifests.publish(claim, "graphs/papers/paper/v1/graph.json.gz", "digest")
    tombstone = manifests.tombstone_documents({}, "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    manifests.commit_tombstone_proof(controls)
    manifests.release_collection_fence("replace-1", tombstone["collection_fence_token"])

    reintroduction = manifests.tombstone_documents({"paper": "fingerprint-2"}, "replace-2")
    assert reintroduction["documents"]["paper"]["status"] == "pending"
    assert reintroduction["pending_tombstone_cleanup_ids"] == [controls[0]["point_id"]]
    assert manifests.tombstone_controls(reintroduction) == []
    fresh_claim = manifests.reserve("paper", "replace-2", "fingerprint-2", mode="replace-collection")
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
    tombstone = manifests.tombstone_documents({}, "replace-1")
    controls = manifests.tombstone_controls(tombstone)
    manifests.commit_tombstone_proof(controls)
    manifests.release_collection_fence("replace-1", tombstone["collection_fence_token"])
    reintroduction = manifests.tombstone_documents({"paper": "fingerprint-2"}, "replace-2")
    claim = manifests.reserve("paper", "replace-2", "fingerprint-2", mode="replace-collection")
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


def test_artifact_read_classifies_gzip_corruption_for_local_fallback():
    objects = InMemoryObjectStore()
    artifacts = GraphArtifactStore(objects, collection="papers")
    key = artifacts.key("paper", 1)
    objects.put(key, b"not-gzip", if_none_match=True, metadata={"artifact_digest": "unused"})

    with pytest.raises(GraphArtifactCorruptionError, match="gzip"):
        artifacts.read(key)


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
    manifests.tombstone_documents({"paper-b": "fp-b"}, "replace-1")
    assert manifests.get("paper-a")["status"] == "tombstoned"
    assert manifests.preflight("paper-a")["allowed"] is False
