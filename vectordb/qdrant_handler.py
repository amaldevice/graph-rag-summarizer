# ============================================================
# QDRANT HANDLER
# Create collection, upload vectors, search vectors
# Support indexing mode and retrieval mode
# ============================================================

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
        collection_name: str = QDRANT_COLLECTION,
        qdrant_backend: str = QDRANT_BACKEND,
        qdrant_url: str = QDRANT_URL,
        qdrant_api_key: str = QDRANT_API_KEY,
        qdrant_host: str = QDRANT_HOST,
        qdrant_port: int = QDRANT_PORT,
    ):
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
        image_url = payload.get("image_url")
        if image_url is None:
            image_urls = payload.get("image_urls") or []
            if image_urls:
                image_url = image_urls[0]

        return {
            "chunk_id": chunk_id,
            "text": payload.get("text", ""),
            "level": payload.get("level", "paragraph"),
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
    def upsert_chunks(self, chunks: list, vectors: list):
        if len(chunks) != len(vectors):
            raise ValueError("Jumlah chunks dan vectors harus sama.")

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

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )
        print(f"✅ Berhasil upload {len(points)} points ke Qdrant")

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
