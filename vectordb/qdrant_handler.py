# ============================================================
# QDRANT HANDLER
# Create collection, upload vectors, search vectors
# Support indexing mode and retrieval mode
# ============================================================

import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from config.settings import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_BACKEND,
    QDRANT_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_URL,
)


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
        collections = self.client.get_collections().collections
        existing_names = [c.name for c in collections]

        if self.collection_name not in existing_names:
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

        return {
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
            chunk_id = int(chunk["chunk_id"])
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
            if image_url:
                payload["image_urls"] = [image_url]

            point = PointStruct(
                id=chunk_id,
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
