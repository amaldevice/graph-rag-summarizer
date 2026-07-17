import sys
from types import SimpleNamespace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from qdrant_client.http.exceptions import ApiException
from qdrant_client.models import PayloadSchemaType

from vectordb.qdrant_handler import QdrantHandler, stable_point_id


def test_search_as_chunks_normalizes_graph_rag_payload() -> None:
    class FakeResult:
        def __init__(self) -> None:
            self.id = 7
            self.score = 0.91
            self.payload = {
                "text": "hello",
                "level": "paragraph",
                "source": "paper.pdf",
                "page": 3,
                "image_urls": ["https://pub.example.r2.dev/images/page-3.png"],
            }

    handler = QdrantHandler(client=object(), collection_name="test")
    handler.search = lambda query_vector, limit=5: [FakeResult()]

    chunks = handler.search_as_chunks([0.1, 0.2], limit=1)

    assert chunks == [{
        "chunk_id": 7,
        "text": "hello",
        "level": "paragraph",
        "hierarchy": {"level": "paragraph", "section": None},
        "layout": {"kind": "paragraph", "page_no": 3},
        "source": "paper.pdf",
        "page_no": 3,
        "image_url": "https://pub.example.r2.dev/images/page-3.png",
        "score": 0.91,
        "rank": 1,
    }]


def test_upsert_chunks_stores_page_and_image_aliases() -> None:
    captured = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            captured["collection_name"] = collection_name
            captured["points"] = points

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.upsert_chunks(
        chunks=[{
            "chunk_id": 1,
            "text": "hello",
            "level": "paragraph",
            "source": "paper.pdf",
            "page_no": 3,
            "image_url": "https://pub.example.r2.dev/images/page-3.png",
        }],
        vectors=[[0.1, 0.2]],
    )

    point = captured["points"][0]
    assert captured["collection_name"] == "test"
    assert point.payload["page_no"] == 3
    assert point.payload["page"] == 3
    assert point.payload["image_url"] == "https://pub.example.r2.dev/images/page-3.png"
    assert point.payload["image_urls"] == ["https://pub.example.r2.dev/images/page-3.png"]
    assert point.payload["hierarchy"] == {"level": "paragraph"}
    assert point.payload["layout"] == {"kind": "paragraph", "page_no": 3}


def test_upsert_chunks_batches_large_uploads() -> None:
    calls = []

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            calls.append((collection_name, points))

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    chunks = [
        {
            "chunk_id": idx,
            "text": f"chunk {idx}",
            "level": "sentence",
            "hierarchy": {"level": "sentence", "section": "A"},
            "layout": {"kind": "sentence", "page_no": 1},
        }
        for idx in range(5)
    ]

    handler.upsert_chunks(chunks, [[0.1, 0.2] for _ in chunks], batch_size=2)

    assert [len(points) for _, points in calls] == [2, 2, 1]
    assert {collection_name for collection_name, _ in calls} == {"test"}
    assert calls[0][1][0].payload["hierarchy"] == {"level": "sentence", "section": "A"}


def test_upsert_chunks_uses_document_safe_point_identity_and_payload() -> None:
    captured = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            captured["collection_name"] = collection_name
            captured["points"] = points

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.upsert_chunks(
        chunks=[{
            "chunk_id": 7,
            "document_id": "paper-a",
            "chunk_uid": "paper-a:chunk:7",
            "text": "hello",
        }],
        vectors=[[0.1, 0.2]],
    )

    point = captured["points"][0]
    assert point.id == stable_point_id("paper-a", 7)
    assert point.payload["document_id"] == "paper-a"
    assert point.payload["chunk_uid"] == "paper-a:chunk:7"
    assert point.payload["chunk_id"] == 7


def test_graph_claim_uses_attempt_points_and_readback_control_proof() -> None:
    objects = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            for point in points:
                objects[str(point.id)] = point

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            return [objects[str(point_id)] for point_id in ids if str(point_id) in objects]

        def scroll(self, **kwargs):
            scroll_filter = kwargs.get("scroll_filter")
            conditions = getattr(scroll_filter, "must", []) if scroll_filter else []

            def matches(point):
                payload = point.payload or {}
                return all(
                    payload.get(condition.key) == condition.match.value
                    for condition in conditions
                    if hasattr(condition, "key") and hasattr(condition, "match")
                )

            return [point for point in objects.values() if matches(point)], None

    from graph.persistent import InMemoryObjectStore, ManifestStore

    manifest = ManifestStore(
        InMemoryObjectStore(),
        collection="papers",
        backend={"kind": "memory", "namespace": "test"},
    )
    claim = manifest.reserve("paper-a", "op-1", "fp-1")
    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    handler.set_graph_claim(manifest, claim)
    point_ids = handler.upsert_chunks(
        [{"chunk_id": 1, "document_id": "paper-a", "chunk_uid": "paper-a:chunk:1", "text": "hello"}],
        [[0.1, 0.2]],
    )
    control_id = handler.write_document_control_point(claim, 2)
    handler.verify_document_control_point(control_id)

    assert point_ids[0] != stable_point_id("paper-a", 1)
    assert objects[point_ids[0]].payload["document_generation"] == claim["document_generation"]
    assert objects[control_id].payload["point_count"] == 1


def test_backfill_materializes_the_standard_document_control_proof() -> None:
    objects = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            del collection_name
            for point in points:
                objects[str(point.id)] = point

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            del collection_name, with_payload, with_vectors
            return [objects[str(point_id)] for point_id in ids if str(point_id) in objects]

        def scroll(self, **kwargs):
            scroll_filter = kwargs.get("scroll_filter")
            conditions = getattr(scroll_filter, "must", []) if scroll_filter else []

            def matches(point):
                payload = point.payload or {}
                return all(
                    payload.get(condition.key) == condition.match.value
                    for condition in conditions
                    if hasattr(condition, "key") and hasattr(condition, "match")
                )

            return [point for point in objects.values() if matches(point)], None

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    objects["chunk-1"] = SimpleNamespace(
        id="chunk-1",
        vector=[0.1, 0.2],
        payload={
            "document_id": "paper-a",
            "chunk_id": 1,
            "chunk_uid": "paper-a:chunk:1",
            "text": "hello",
            "vector_point": True,
            "graph_point": False,
            "document_generation": 2,
        },
    )
    from graph.persistent import InMemoryObjectStore, ManifestStore, source_fingerprint

    chunks = handler.scroll_document_chunks(document_id="paper-a", include_vectors=True)
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve(
        "paper-a",
        "backfill:papers:paper-a",
        source_fingerprint(chunks, "paper-a"),
        document_generation=2,
    )

    handler.materialize_backfill_claim(manifests, claim)
    handler.verify_graph_claim_current(claim)

    control = next(point for point in objects.values() if point.payload.get("graph_control_point") == "document")
    assert control.id == handler._last_control_id
    attempted_chunk = next(point for point in objects.values() if point.payload.get("source_point_id") == "chunk-1")
    assert attempted_chunk.id != "chunk-1"
    assert attempted_chunk.payload["document_attempt_id"] == claim["pending_attempt_id"]
    assert objects["chunk-1"].payload["backfill_retired"] is True
    assert objects["chunk-1"].payload["vector_point"] is False
    assert manifests.get("paper-a")["vector_ready"] is True

    attempted_chunk.payload["document_generation"] = 3

    with pytest.raises(RuntimeError, match="point-set proof"):
        handler.verify_graph_claim_current(claim)


def test_backfill_retries_partial_materialization_with_same_attempt_points() -> None:
    objects = {}

    class FakeClient:
        def __init__(self) -> None:
            self.fail_after_attempt_upsert = True
            self.materialized_vectors = []
            self.embedding_calls = 0

        def upsert(self, collection_name, points) -> None:
            del collection_name
            points = list(points)
            for point in points:
                objects[str(point.id)] = point
            if any(point.payload.get("source_point_id") == "chunk-1" for point in points):
                self.materialized_vectors.append([list(point.vector) for point in points])
                if self.fail_after_attempt_upsert:
                    self.fail_after_attempt_upsert = False
                    raise RuntimeError("interrupted after attempt upsert")

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            del collection_name, with_payload, with_vectors
            return [objects[str(point_id)] for point_id in ids if str(point_id) in objects]

        def scroll(self, **kwargs):
            scroll_filter = kwargs.get("scroll_filter")
            conditions = getattr(scroll_filter, "must", []) if scroll_filter else []

            def matches(point):
                payload = point.payload or {}
                return all(
                    payload.get(condition.key) == condition.match.value
                    for condition in conditions
                    if hasattr(condition, "key") and hasattr(condition, "match")
                )

            return [point for point in objects.values() if matches(point)], None

    client = FakeClient()
    handler = QdrantHandler(client=client, collection_name="papers")
    objects["chunk-1"] = SimpleNamespace(
        id="chunk-1",
        vector=[0.1, 0.2],
        payload={
            "document_id": "paper-a",
            "chunk_id": 1,
            "chunk_uid": "paper-a:chunk:1",
            "text": "hello",
            "vector_point": True,
            "graph_point": False,
            "document_generation": 2,
        },
    )
    from graph.persistent import InMemoryObjectStore, ManifestStore, source_fingerprint

    chunks = handler.scroll_document_chunks(document_id="paper-a", include_vectors=True)
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve(
        "paper-a",
        "backfill:papers:paper-a",
        source_fingerprint(chunks, "paper-a"),
        document_generation=2,
    )

    with pytest.raises(RuntimeError, match="interrupted after attempt upsert"):
        handler.materialize_backfill_claim(manifests, claim)

    partial_attempt = next(point for point in objects.values() if point.payload.get("source_point_id") == "chunk-1")
    assert objects["chunk-1"].payload.get("backfill_retired") is None

    handler.materialize_backfill_claim(manifests, claim)
    handler.verify_graph_claim_current(claim)

    retry_attempts = [point for point in objects.values() if point.payload.get("source_point_id") == "chunk-1"]
    assert [point.id for point in retry_attempts] == [partial_attempt.id]
    assert client.materialized_vectors == [[[0.1, 0.2]], [[0.1, 0.2]]]
    assert client.embedding_calls == 0
    assert objects["chunk-1"].payload["backfill_retired"] is True
    assert manifests.get("paper-a")["vector_ready"] is True


def test_backfill_retires_stale_attempt_duplicate_before_reproof() -> None:
    objects = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            del collection_name
            for point in points:
                objects[str(point.id)] = point

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            del collection_name, with_payload, with_vectors
            return [objects[str(point_id)] for point_id in ids if str(point_id) in objects]

        def scroll(self, **kwargs):
            scroll_filter = kwargs.get("scroll_filter")
            conditions = getattr(scroll_filter, "must", []) if scroll_filter else []

            def matches(point):
                payload = point.payload or {}
                return all(
                    payload.get(condition.key) == condition.match.value
                    for condition in conditions
                    if hasattr(condition, "key") and hasattr(condition, "match")
                )

            return [point for point in objects.values() if matches(point)], None

    source_payload = {
        "document_id": "paper-a",
        "chunk_id": 1,
        "chunk_uid": "paper-a:chunk:1",
        "text": "hello",
        "vector_point": True,
        "graph_point": False,
        "document_generation": 2,
    }
    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    objects["chunk-1"] = SimpleNamespace(
        id="chunk-1",
        vector=[0.1, 0.2],
        payload=source_payload,
    )
    from graph.persistent import InMemoryObjectStore, ManifestStore, source_fingerprint

    source_fingerprint_value = source_fingerprint(
        [handler._normalize_chunk_payload(source_payload, fallback_chunk_id="chunk-1")],
        "paper-a",
    )
    manifests = ManifestStore(InMemoryObjectStore(), collection="papers")
    claim = manifests.reserve(
        "paper-a",
        "backfill:papers:paper-a",
        source_fingerprint_value,
        document_generation=2,
    )
    stale_attempt_id = "8e5e4a42-f96d-5d85-a65d-c6ca4267b412"
    objects[stale_attempt_id] = SimpleNamespace(
        id=stale_attempt_id,
        vector=[0.1, 0.2],
        payload={
            **source_payload,
            "source_point_id": "chunk-1",
            "source_fingerprint": source_fingerprint_value,
            "document_attempt_id": "old-attempt",
            "document_fence_token": 1,
            "collection_fence_token": 0,
            "collection_attempt_id": None,
        },
    )

    handler.materialize_backfill_claim(manifests, claim)
    handler.verify_graph_claim_current(claim)

    active_attempts = [
        point for point in objects.values()
        if point.payload.get("document_attempt_id") == claim["pending_attempt_id"]
        and point.payload.get("vector_point") is True
    ]
    assert len(active_attempts) == 1
    assert active_attempts[0].payload["source_point_id"] == "chunk-1"
    assert objects["chunk-1"].payload["backfill_retired"] is True
    assert objects[stale_attempt_id].payload["backfill_retired"] is True
    assert manifests.get("paper-a")["vector_ready"] is True


def test_tombstone_proof_enumerates_the_complete_qdrant_deny_set() -> None:
    objects = {}

    class FakeClient:
        def upsert(self, collection_name, points) -> None:
            del collection_name
            for point in points:
                objects[str(point.id)] = point

        def scroll(self, **kwargs):
            del kwargs
            return list(objects.values()), None

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    controls = handler.write_tombstone_control_points(
        [{"document_id": "paper-a", "document_generation": 1, "tombstone_attempt_id": "op:paper-a"}],
        epoch=1,
        operation_id="op",
        fence_token=4,
        vector_size=2,
    )
    objects["extra"] = SimpleNamespace(
        id="extra",
        payload={
            "graph_control_point": "tombstone",
            "graph_tombstoned": True,
            "tombstone_complete": True,
        },
    )

    with pytest.raises(RuntimeError, match="tombstone"):
        handler.verify_tombstone_control_points(controls)


def test_qdrant_search_pushes_active_generation_and_plane_filters_server_side() -> None:
    captured = {}

    class FakeClient:
        def search(self, **kwargs):
            captured.update(kwargs)
            return []

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    handler.set_denied_document_ids(["gone"])
    handler.set_active_vector_generations({"paper-a": 2})
    handler.search([0.1, 0.2], limit=3)

    query_filter = captured["query_filter"].model_dump(exclude_none=True)
    assert captured["limit"] == 3
    serialized = str(query_filter)
    assert "document_generation" in serialized
    assert "graph_point" in serialized
    assert "gone" in serialized


def test_qdrant_search_fails_closed_when_manifest_has_no_active_vectors() -> None:
    class FakeClient:
        def search(self, **kwargs):
            raise AssertionError("backend search must not run without active generations")

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    handler.set_active_vector_generations({})

    assert handler.search([0.1, 0.2], limit=3) == []


def test_replace_collection_baseline_does_not_delete_graph_controls_unless_explicitly_cleaned():
    calls = []

    class FakeClient:
        def scroll(self, **kwargs):
            del kwargs
            return [
                SimpleNamespace(id="old-vector", payload={"document_id": "paper-a", "vector_point": True}),
                SimpleNamespace(id="old-document-control", payload={"graph_control_point": "document", "document_id": "paper-a"}),
                SimpleNamespace(id="old-tombstone", payload={
                    "graph_control_point": "tombstone",
                    "document_id": "paper-old",
                    "document_generation": 1,
                    "tombstone_epoch": 2,
                    "tombstone_operation_id": "replace-old",
                    "tombstone_attempt_id": "attempt-old",
                    "tombstone_fence_token": 3,
                    "collection_fence_token": 3,
                }),
            ], None

        def delete(self, **kwargs):
            calls.append(kwargs)

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")
    handler.capture_collection_baseline()
    handler.finalize_replace_collection(
        ["new-vector", "new-document-control"],
        keep_control_ids={"new-document-control"},
        remove_control_ids={"old-tombstone"},
    )

    assert calls[0]["points_selector"].points == ["old-vector"]
    assert calls[1]["points_selector"].must[0].has_id == ["old-tombstone"]


def test_scroll_point_records_rejects_repeated_offset() -> None:
    class FakeClient:
        calls = 0

        def scroll(self, **kwargs):
            del kwargs
            self.calls += 1
            if self.calls == 1:
                return [SimpleNamespace(id="p1", payload={"document_id": "paper-a"})], "cursor"
            return [], "cursor"

    handler = QdrantHandler(client=FakeClient(), collection_name="papers")

    with pytest.raises(RuntimeError, match="repeated offset"):
        handler._scroll_point_records()


def test_search_as_chunks_preserves_document_identity() -> None:
    class FakeResult:
        id = stable_point_id("paper-a", 7)
        score = 0.8
        payload = {
            "chunk_id": 7,
            "chunk_uid": "paper-a:chunk:7",
            "document_id": "paper-a",
            "text": "hello",
        }

    handler = QdrantHandler(client=object(), collection_name="test")
    handler.search = lambda query_vector, limit=5: [FakeResult()]

    chunk = handler.search_as_chunks([0.1, 0.2], limit=1)[0]

    assert chunk["chunk_id"] == 7
    assert chunk["chunk_uid"] == "paper-a:chunk:7"
    assert chunk["document_id"] == "paper-a"


def test_expand_parent_context_fetches_bounded_parent_points() -> None:
    paragraph_id = stable_point_id("paper-a", 1)
    section_id = stable_point_id("paper-a", 0)

    class FakeClient:
        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            assert collection_name == "test"
            assert with_payload is True
            assert with_vectors is False
            if ids == [paragraph_id]:
                return [SimpleNamespace(
                    id=paragraph_id,
                    payload={
                        "chunk_id": 1,
                        "chunk_uid": "paper-a:chunk:1",
                        "document_id": "paper-a",
                        "text": "Paragraph context.",
                        "level": "paragraph",
                        "hierarchy": {
                            "paragraph_id": "paragraph:1",
                            "parent_id": "section:1",
                            "parent_point_id": section_id,
                        },
                    },
                )]
            assert ids == [section_id]
            return [SimpleNamespace(
                id=section_id,
                payload={
                    "chunk_id": 0,
                    "chunk_uid": "paper-a:chunk:0",
                    "document_id": "paper-a",
                    "text": "Findings",
                    "level": "section",
                    "hierarchy": {"section_id": "section:1"},
                },
            )]

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    chunks = [{
        "chunk_id": 2,
        "chunk_uid": "paper-a:chunk:2",
        "document_id": "paper-a",
        "text": "A sufficiently long sentence contains evidence.",
        "level": "sentence",
        "hierarchy": {
            "paragraph_id": "paragraph:1",
            "parent_id": "paragraph:1",
            "parent_point_id": paragraph_id,
        },
    }]

    result = handler.expand_parent_context(chunks, max_depth=2)

    assert [item["chunk_id"] for item in result[0]["parent_context"]] == ["paper-a:chunk:1", "paper-a:chunk:0"]
    assert result[0]["parent_context"][0]["reason"] == "hierarchy_parent"


def test_expand_parent_context_reports_unavailable_without_breaking_retrieval() -> None:
    class FakeClient:
        def retrieve(self, **kwargs):
            del kwargs
            raise ApiException("remote unavailable")

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    chunks = [{
        "chunk_id": 2,
        "document_id": "paper-a",
        "hierarchy": {"parent_chunk_id": 1},
    }]

    result = handler.expand_parent_context(chunks)

    assert result[0]["parent_context"] == []
    assert result[0]["parent_context_status"]["status"] == "unavailable"
    assert result[0]["parent_context_status"]["reason"] == "ApiException"


def test_expand_parent_context_keeps_legacy_payloads_readable():
    class FakeClient:
        def retrieve(self, **kwargs):
            raise AssertionError("legacy payload should not trigger a parent lookup")

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    chunks = [{"chunk_id": 2, "text": "Legacy sentence.", "level": "sentence", "hierarchy": {"level": "sentence"}}]

    result = handler.expand_parent_context(chunks)

    assert result[0]["parent_context"] == []
    assert result[0]["parent_context_status"]["status"] == "not_present"


def test_expand_parent_context_preserves_fetched_parents_on_partial_failure() -> None:
    paragraph_id = stable_point_id("paper-a", 1)

    class FakeClient:
        calls = 0

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            del collection_name, ids, with_payload, with_vectors
            self.calls += 1
            if self.calls == 1:
                return [SimpleNamespace(
                    id=paragraph_id,
                    payload={
                        "chunk_id": 1,
                        "document_id": "paper-a",
                        "chunk_uid": "paper-a:chunk:1",
                        "text": "Paragraph context.",
                        "level": "paragraph",
                        "hierarchy": {"parent_point_id": stable_point_id("paper-a", 0)},
                    },
                )]
            raise ApiException("section unavailable")

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    chunks = [{
        "chunk_id": 2,
        "document_id": "paper-a",
        "hierarchy": {"parent_point_id": paragraph_id},
    }]

    result = handler.expand_parent_context(chunks)

    assert [item["chunk_id"] for item in result[0]["parent_context"]] == ["paper-a:chunk:1"]
    assert result[0]["parent_context_status"]["status"] == "partial"


def test_prepare_ingest_append_rejects_duplicate_document() -> None:
    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def create_payload_index(self, **kwargs):
            del kwargs

        def scroll(self, **kwargs):
            del kwargs
            return [], None

        def count(self, collection_name, count_filter, exact=True):
            del collection_name, count_filter, exact
            return SimpleNamespace(count=1)

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    with pytest.raises(ValueError, match="already exists"):
        handler.prepare_ingest("append", "paper-a", vector_size=2)


def test_prepare_ingest_append_accepts_points_from_the_same_interrupted_claim() -> None:
    claim = {
        "document_generation": 3,
        "pending_attempt_id": "attempt-3",
    }

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def create_payload_index(self, **kwargs):
            del kwargs

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(
                id="graph-point",
                payload={
                    "document_id": "paper-a",
                    "document_generation": 3,
                    "document_attempt_id": "attempt-3",
                    "vector_point": True,
                    "graph_point": True,
                },
            )], None

        def count(self, collection_name, count_filter, exact=True):
            del collection_name, count_filter, exact
            return SimpleNamespace(count=1)

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    handler.prepare_ingest("append", "paper-a", vector_size=2, claim=claim)


def test_prepare_ingest_indexes_every_payload_field_used_by_cloud_filters() -> None:
    created = []

    class FakeClient:
        def __init__(self) -> None:
            self.payload_schema = {}

        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def get_collection(self, collection_name):
            assert collection_name == "test"
            return SimpleNamespace(payload_schema=self.payload_schema)

        def create_payload_index(self, **kwargs):
            created.append((kwargs["field_name"], kwargs["field_schema"]))
            self.payload_schema[kwargs["field_name"]] = kwargs["field_schema"]

        def scroll(self, **kwargs):
            del kwargs
            return [], None

        def count(self, collection_name, count_filter, exact=True):
            del collection_name, count_filter, exact
            return SimpleNamespace(count=0)

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    handler.prepare_ingest("append", "paper-a", vector_size=2)

    assert dict(created) == {
        "document_id": PayloadSchemaType.KEYWORD,
        "document_generation": PayloadSchemaType.INTEGER,
        "document_attempt_id": PayloadSchemaType.KEYWORD,
        "vector_point": PayloadSchemaType.BOOL,
        "graph_point": PayloadSchemaType.BOOL,
        "graph_control_point": PayloadSchemaType.KEYWORD,
        "graph_tombstoned": PayloadSchemaType.BOOL,
        "tombstone_epoch": PayloadSchemaType.INTEGER,
        "tombstone_operation_id": PayloadSchemaType.KEYWORD,
        "tombstone_attempt_id": PayloadSchemaType.KEYWORD,
        "tombstone_fence_token": PayloadSchemaType.INTEGER,
        "collection_fence_token": PayloadSchemaType.INTEGER,
        "collection_attempt_id": PayloadSchemaType.KEYWORD,
    }


def test_prepare_ingest_indexes_provenance_fields_before_control_proof() -> None:
    objects = {}

    class StrictFakeClient:
        def __init__(self) -> None:
            self.payload_schema = {}

        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def get_collection(self, collection_name):
            assert collection_name == "test"
            return SimpleNamespace(payload_schema=self.payload_schema)

        def create_payload_index(self, **kwargs):
            self.payload_schema[kwargs["field_name"]] = kwargs["field_schema"]

        def count(self, collection_name, count_filter, exact=True):
            del collection_name, count_filter, exact
            return SimpleNamespace(count=0)

        def upsert(self, collection_name, points) -> None:
            assert collection_name == "test"
            for point in points:
                objects[str(point.id)] = point

        def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
            del collection_name, with_payload, with_vectors
            return [objects[str(point_id)] for point_id in ids if str(point_id) in objects]

        def scroll(self, **kwargs):
            scroll_filter = kwargs.get("scroll_filter")
            conditions = getattr(scroll_filter, "must", []) if scroll_filter else []
            for condition in conditions:
                if hasattr(condition, "key") and condition.key not in self.payload_schema:
                    raise RuntimeError(f"missing payload index: {condition.key}")

            def matches(point):
                payload = point.payload or {}
                return all(
                    payload.get(condition.key) == condition.match.value
                    for condition in conditions
                    if hasattr(condition, "key") and hasattr(condition, "match")
                )

            return [point for point in objects.values() if matches(point)], None

    from graph.persistent import InMemoryObjectStore, ManifestStore

    manifests = ManifestStore(InMemoryObjectStore(), collection="test")
    claim = manifests.reserve("paper-a", "op-1", "fingerprint")
    handler = QdrantHandler(client=StrictFakeClient(), collection_name="test")
    handler.set_graph_claim(manifests, claim)

    handler.prepare_ingest("append", "paper-a", vector_size=2, claim=claim)
    handler.upsert_chunks(
        [{"chunk_id": 1, "document_id": "paper-a", "chunk_uid": "paper-a:chunk:1", "text": "hello"}],
        [[0.1, 0.2]],
    )
    control_id = handler.write_document_control_point(claim, 2)

    handler.verify_document_control_point(control_id)


def test_replace_document_deletes_only_stale_points_for_document() -> None:
    calls = []

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def create_payload_index(self, **kwargs):
            calls.append(("index", kwargs))

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(id="paper-a:old", payload={"document_id": "paper-a"})], None

        def delete(self, collection_name, points_selector, wait=True):
            calls.append(("delete", collection_name, points_selector, wait))

        def create_collection(self, **kwargs):
            calls.append(("create", kwargs))

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.prepare_ingest("replace-document", "paper-a", vector_size=2)
    handler.finalize_replace_document("paper-a", ["paper-a:new"])

    assert calls[0][0] == "index"
    assert calls[-1][0] == "delete"
    assert calls[-1][1] == "test"
    assert calls[-1][2].points == ["paper-a:old"]


def test_prepare_ingest_replace_collection_keeps_collection_until_finalize() -> None:
    calls = []

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(id="old", payload=None)], None

        def delete(self, collection_name, points_selector, wait=True):
            calls.append((collection_name, points_selector, wait))

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.prepare_ingest("replace-collection", "paper-a", vector_size=2)
    handler.finalize_replace_collection(["new"])

    assert len(calls) == 1
    assert calls[0][0] == "test"


def test_prepare_ingest_rejects_legacy_points_for_document_operations() -> None:
    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(id=1, payload={"text": "legacy"})], None

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    with pytest.raises(ValueError, match="legacy points"):
        handler.prepare_ingest("append", "paper-a", vector_size=2)

    with pytest.raises(ValueError, match="legacy points"):
        handler.prepare_ingest("replace-document", "paper-a", vector_size=2)


def test_prepare_ingest_allows_legacy_points_for_legacy_vector_append() -> None:
    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(id=1, payload={"text": "legacy"})], None

        def count(self, **kwargs):
            del kwargs
            return SimpleNamespace(count=0)

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    handler.prepare_ingest(
        "append",
        "paper-a",
        vector_size=2,
        allow_legacy_append=True,
    )


def test_prepare_ingest_rejects_raw_legacy_points_for_replace_document() -> None:
    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def scroll(self, **kwargs):
            del kwargs
            return [SimpleNamespace(id=1, payload={"text": "legacy"})], None

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    with pytest.raises(ValueError, match="cannot safely select"):
        handler.prepare_ingest(
            "replace-document",
            "paper-a",
            vector_size=2,
            allow_legacy_append=True,
        )


def test_legacy_scan_continues_after_legacy_point_to_detect_later_pagination_failure() -> None:
    class FakeClient:
        calls = 0

        def create_payload_index(self, **kwargs):
            del kwargs

        def scroll(self, **kwargs):
            del kwargs
            self.calls += 1
            if self.calls == 1:
                return [
                    SimpleNamespace(id="legacy", payload={"text": "legacy"}),
                    SimpleNamespace(id="control", payload={"graph_control_point": "tombstone"}),
                ], "cursor"
            return [], "cursor"

    handler = QdrantHandler(client=FakeClient(), collection_name="test")

    with pytest.raises(RuntimeError, match="repeated offset"):
        handler.has_legacy_points()


def test_two_document_append_points_keep_distinct_ids() -> None:
    calls = []

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="test")])

        def create_payload_index(self, **kwargs):
            del kwargs

        def scroll(self, **kwargs):
            del kwargs
            return [], None

        def count(self, collection_name, count_filter, exact=True):
            del collection_name, count_filter, exact
            return SimpleNamespace(count=0)

        def upsert(self, collection_name, points):
            del collection_name
            calls.extend(points)

    handler = QdrantHandler(client=FakeClient(), collection_name="test")
    handler.prepare_ingest("append", "paper-a", vector_size=2)
    handler.upsert_chunks([{"chunk_id": 0, "document_id": "paper-a", "text": "A"}], [[0.1, 0.2]])
    handler.prepare_ingest("append", "paper-b", vector_size=2)
    handler.upsert_chunks([{"chunk_id": 0, "document_id": "paper-b", "text": "B"}], [[0.1, 0.2]])

    assert len(calls) == 2
    assert len({point.id for point in calls}) == 2
