import gzip
import hashlib
import json

import networkx as nx

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


def test_manifest_reserves_versions_and_publishes_only_validated_artifact():
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers", backend={"kind": "memory", "namespace": "test"})
    artifacts = GraphArtifactStore(objects, collection="papers")

    claim = manifests.reserve("paper", "op-1", "fingerprint-1", mode="append")
    assert claim["pending_version"] == 1
    key, digest = artifacts.write(claim, b'{"document_id":"paper"}')
    published = manifests.publish(claim, key, digest)
    assert published["status"] == "available"
    assert published["active_version"] == 1

    replacement = manifests.reserve("paper", "op-2", "fingerprint-2", mode="replace-document")
    assert replacement["pending_version"] == 2
    assert manifests.get("paper")["status"] == "pending"
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
    manifests.publish(claim, "graphs/papers/paper-a/v1/graph.json.gz", "a")
    manifests.tombstone_documents({"paper-b"}, "replace-1")
    assert manifests.get("paper-a")["status"] == "tombstoned"
    assert manifests.preflight("paper-a")["allowed"] is False
