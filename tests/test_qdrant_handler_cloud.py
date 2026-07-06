import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vectordb.qdrant_handler import QdrantHandler


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
