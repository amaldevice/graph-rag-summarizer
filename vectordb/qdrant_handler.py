# ============================================================
# QDRANT HANDLER
# Create collection, upload vectors, search vectors
# Support indexing mode and retrieval mode
# ============================================================

import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    IsEmptyCondition,
    MatchValue,
    PayloadSchemaType,
    PayloadField,
    PointIdsList,
    PointStruct,
    VectorParams,
)
from launcher.contract import build_chunk_uid

from config.settings import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_BACKEND,
    QDRANT_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_URL,
)


def stable_point_id(document_id: str, chunk_id) -> str:
    """Return a deterministic UUID accepted by Qdrant for a document chunk."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"graph-rag:{build_chunk_uid(document_id, chunk_id)}"))


class QdrantHandler:
    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
        qdrant_backend: str | None = None,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
        qdrant_host: str | None = None,
        qdrant_port: int | None = None,
    ):
        collection_name = collection_name or os.getenv("QDRANT_COLLECTION", QDRANT_COLLECTION)
        qdrant_backend = (qdrant_backend or os.getenv("QDRANT_BACKEND", QDRANT_BACKEND)).lower()
        qdrant_url = qdrant_url if qdrant_url is not None else os.getenv("QDRANT_URL", QDRANT_URL)
        qdrant_api_key = qdrant_api_key if qdrant_api_key is not None else os.getenv("QDRANT_API_KEY", QDRANT_API_KEY)
        qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", QDRANT_HOST)
        qdrant_port = int(qdrant_port or os.getenv("QDRANT_PORT", QDRANT_PORT))

        if client is not None:
            self.client = client
        else:
            backend = qdrant_backend.lower()
            if backend == "auto":
                backend = "cloud" if qdrant_url else "local"

            if backend == "cloud":
                if not qdrant_url:
                    raise ValueError("QDRANT_URL is required when QDRANT_BACKEND=cloud")
                self.client = QdrantClient(
                    url=qdrant_url,
                    api_key=qdrant_api_key or None,
                    timeout=60,
                )
            elif backend == "local":
                self.client = QdrantClient(host=qdrant_host, port=qdrant_port)
            else:
                raise ValueError(f"Unsupported Qdrant backend: {qdrant_backend}")

        self.collection_name = collection_name

    # ========================================================
    # CREATE COLLECTION
    # Buat collection jika belum ada
    # ========================================================
    def create_collection_if_not_exists(self, vector_size: int | None = None):
        if not self.collection_exists():
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size or EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            print(f"✅ Collection '{self.collection_name}' berhasil dibuat")
        else:
            print(f"✅ Collection '{self.collection_name}' sudah ada")

    def collection_exists(self) -> bool:
        collections = self.client.get_collections().collections
        return self.collection_name in {collection.name for collection in collections}

    def _document_filter(self, document_id: str) -> Filter:
        return Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        )

    def _ensure_document_id_index(self) -> None:
        create_index = getattr(self.client, "create_payload_index", None)
        if create_index is None:
            return
        get_collection = getattr(self.client, "get_collection", None)
        if get_collection is not None:
            info = get_collection(self.collection_name)
            if "document_id" in (getattr(info, "payload_schema", None) or {}):
                return
        create_index(
            collection_name=self.collection_name,
            field_name="document_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def document_exists(self, document_id: str) -> bool:
        self._ensure_document_id_index()
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=self._document_filter(document_id),
            exact=True,
        )
        return int(result.count) > 0

    def has_legacy_points(self) -> bool:
        """Detect points created before document_id was part of the payload contract."""
        scroll = getattr(self.client, "scroll", None)
        if scroll is None:
            raise RuntimeError("Qdrant client cannot verify legacy document metadata")
        self._ensure_document_id_index()
        points, _ = scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[
                    IsEmptyCondition(
                        is_empty=PayloadField(key="document_id"),
                    )
                ]
            ),
            limit=256,
            with_payload=["document_id"],
            with_vectors=False,
        )
        return any(
            not isinstance((point.payload or {}).get("document_id"), str)
            or not (point.payload or {}).get("document_id", "").strip()
            for point in points
        )

    def delete_document(self, document_id: str) -> None:
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._document_filter(document_id),
            wait=True,
        )

    def prepare_ingest(self, ingest_mode: str, document_id: str, vector_size: int) -> None:
        """Apply one explicit collection lifecycle operation before upload."""
        ingest_mode = (ingest_mode or "append").strip().lower()
        if ingest_mode not in {"append", "replace-document", "replace-collection"}:
            raise ValueError(f"Unsupported ingest mode: {ingest_mode}")
        if not document_id or not document_id.strip():
            raise ValueError("document_id is required for ingest")

        exists = self.collection_exists()

        if ingest_mode == "append":
            if exists and self.has_legacy_points():
                raise ValueError(
                    f"Collection '{self.collection_name}' contains legacy points without document_id; "
                    "use replace-collection to rebuild it before append"
                )
            if exists and self.document_exists(document_id):
                raise ValueError(
                    f"Document '{document_id}' already exists in collection '{self.collection_name}'"
                )
            self.create_collection_if_not_exists(vector_size=vector_size)
        elif ingest_mode == "replace-document":
            if exists:
                if self.has_legacy_points():
                    raise ValueError(
                        f"Collection '{self.collection_name}' contains legacy points without document_id; "
                        "use replace-collection to rebuild it before replace-document"
                    )
                self._ensure_document_id_index()
            self.create_collection_if_not_exists(vector_size=vector_size)
        else:
            # Keep old points until the new upload succeeds; finalize_replace_collection
            # removes them by ID after the caller has a complete point set.
            self.create_collection_if_not_exists(vector_size=vector_size)

        self._ensure_document_id_index()

    def _normalize_chunk_payload(self, payload: dict, fallback_chunk_id, score=None, rank=None):
        chunk_id = payload.get("chunk_id", fallback_chunk_id)
        try:
            chunk_id = int(chunk_id)
        except (TypeError, ValueError):
            pass

        page_no = payload.get("page_no", payload.get("page"))
        level = payload.get("level", "paragraph")
        hierarchy = dict(payload.get("hierarchy") or {})
        hierarchy.setdefault("level", level)
        hierarchy.setdefault("section", payload.get("section"))
        layout = dict(payload.get("layout") or {})
        layout.setdefault("kind", payload.get("layout_kind", level))
        layout.setdefault("page_no", page_no)
        image_url = payload.get("image_url")
        if image_url is None:
            image_urls = payload.get("image_urls") or []
            if image_urls:
                image_url = image_urls[0]

        normalized = {
            "chunk_id": chunk_id,
            "text": payload.get("text", ""),
            "level": level,
            "hierarchy": hierarchy,
            "layout": layout,
            "source": payload.get("source", "docling"),
            "page_no": page_no,
            "image_url": image_url,
            "score": score,
            "rank": rank,
        }
        if payload.get("document_id") is not None:
            normalized["document_id"] = payload["document_id"]
        if payload.get("chunk_uid") is not None:
            normalized["chunk_uid"] = payload["chunk_uid"]
        elif payload.get("document_id") is not None:
            normalized["chunk_uid"] = build_chunk_uid(payload["document_id"], chunk_id)
        return normalized

    def _chunk_payload(self, chunk: dict) -> tuple[dict, str | int]:
        chunk_id = int(chunk["chunk_id"])
        document_id = str(chunk.get("document_id") or "").strip()
        chunk_uid = chunk.get("chunk_uid")
        if document_id:
            chunk_uid = chunk_uid or build_chunk_uid(document_id, chunk_id)
            point_id = stable_point_id(document_id, chunk_id)
        else:
            point_id = chunk.get("point_id", chunk_id)

        page_no = chunk.get("page_no", chunk.get("page"))
        image_url = chunk.get("image_url")
        if image_url is None:
            image_urls = chunk.get("image_urls") or []
            if image_urls:
                image_url = image_urls[0]

        payload = {
            "chunk_id": chunk_id,
            "text": chunk.get("text", ""),
            "level": chunk.get("level", "paragraph"),
            "hierarchy": chunk.get("hierarchy") or {"level": chunk.get("level", "paragraph")},
            "layout": chunk.get("layout") or {"kind": chunk.get("level", "paragraph"), "page_no": page_no},
            "source": chunk.get("source", "docling"),
            "page_no": page_no,
            "page": page_no,
            "image_url": image_url,
        }
        if document_id:
            payload["document_id"] = document_id
            payload["chunk_uid"] = chunk_uid
        if image_url:
            payload["image_urls"] = [image_url]
        return payload, point_id

    # ========================================================
    # UPSERT CHUNKS
    # Simpan vector + payload ke Qdrant
    # ========================================================
    def upsert_chunks(self, chunks: list, vectors: list, batch_size: int = 256):
        if len(chunks) != len(vectors):
            raise ValueError("Jumlah chunks dan vectors harus sama.")
        # ponytail: fixed-size batches beat fragile byte estimation; tune only if Qdrant limits differ.
        batch_size = max(1, int(batch_size))

        points = []
        for chunk, vector in zip(chunks, vectors):
            payload, point_id = self._chunk_payload(chunk)

            point = PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
            points.append(point)

        total_batches = (len(points) + batch_size - 1) // batch_size
        for batch_number, start in enumerate(range(0, len(points), batch_size), start=1):
            batch = points[start:start + batch_size]
            if total_batches > 1:
                print(f"⬆️ Upload batch {batch_number}/{total_batches}: {len(batch)} points")
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )
        print(f"✅ Berhasil upload {len(points)} points ke Qdrant ({total_batches} batch)")
        return [point.id for point in points]

    def finalize_replace_collection(self, keep_point_ids: list) -> None:
        """Remove pre-existing points after a replacement upload has completed."""
        keep = {str(point_id) for point_id in keep_point_ids}
        stale_ids = [point_id for point_id in self._scroll_point_ids() if str(point_id) not in keep]

        if stale_ids:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=stale_ids),
                wait=True,
            )
        print(f"✅ Replace-collection selesai; {len(stale_ids)} legacy points dihapus")

    def finalize_replace_document(self, document_id: str, keep_point_ids: list) -> None:
        """Remove stale points for one document after its replacement upload completes."""
        keep = {str(point_id) for point_id in keep_point_ids}
        stale_ids = [
            point_id
            for point_id in self._scroll_point_ids(self._document_filter(document_id))
            if str(point_id) not in keep
        ]

        if stale_ids:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=stale_ids),
                wait=True,
            )
        print(f"✅ Replace-document selesai; {len(stale_ids)} stale points dihapus")

    def _scroll_point_ids(self, scroll_filter: Filter | None = None) -> list:
        scroll_offset = None
        point_ids = []
        while True:
            points, scroll_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=256,
                offset=scroll_offset,
                with_payload=False,
                with_vectors=False,
            )
            point_ids.extend(point.id for point in points)
            if scroll_offset is None:
                break
        return point_ids

    # ========================================================
    # SEARCH RAW RESULTS
    # Cari chunk paling relevan dari query vector
    # ========================================================
    def search(self, query_vector: list, limit: int = 5):
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return results

    # ========================================================
    # SEARCH AS CHUNKS
    # Kembalikan hasil search langsung dalam format chunk dict
    # ========================================================
    def search_as_chunks(self, query_vector: list, limit: int = 5):
        results = self.search(query_vector=query_vector, limit=limit)

        retrieved_chunks = []
        for rank, result in enumerate(results):
            payload = result.payload or {}
            retrieved_chunks.append(
                self._normalize_chunk_payload(
                    payload,
                    fallback_chunk_id=result.id,
                    score=getattr(result, "score", None),
                    rank=rank + 1,
                )
            )

        return retrieved_chunks
