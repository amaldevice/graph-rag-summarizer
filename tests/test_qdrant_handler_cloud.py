import sys
from types import SimpleNamespace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from qdrant_client.http.exceptions import ApiException

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
    assert objects[control_id].payload["point_count"] == 1


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
