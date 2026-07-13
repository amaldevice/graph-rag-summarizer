# ============================================================
# QDRANT HANDLER
# Create collection, upload vectors, search vectors
# Support indexing mode and retrieval mode
# ============================================================

import os
import hashlib
from uuid import NAMESPACE_URL, uuid5
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ApiException, ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    Distance,
    Condition,
    FieldCondition,
    Filter,
    HasIdCondition,
    IsEmptyCondition,
    MatchValue,
    PayloadSchemaType,
    PayloadField,
    PointIdsList,
    PointStruct,
    VectorParams,
)
from launcher.contract import build_chunk_uid, build_stable_point_id

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
    return build_stable_point_id(document_id, chunk_id)


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
        self._mutation_guard = None
        self._graph_claim = None
        self._collection_claim = None
        self._denied_document_ids = set()
        self._active_vector_generations = None
        self._active_graph_selectors = {}

    def set_graph_claim(self, manifests, claim: dict) -> None:
        """Require a current manifest claim before graph-stage Qdrant writes."""
        self._graph_claim = dict(claim)

        def guard(operation):
            result = manifests.mutate_claim(self._graph_claim, operation)
            manifests.assert_claim_current(self._graph_claim)
            return result

        self._mutation_guard = guard

    def set_collection_claim(self, manifests, operation_id: str, fence_token: int, attempt_id: str | None = None) -> None:
        self._collection_claim = (manifests, operation_id, int(fence_token), attempt_id)

        def guard(operation):
            return manifests.mutate_collection(operation_id, int(fence_token), operation, attempt_id)

        self._mutation_guard = guard

    def _mutate(self, operation):
        return self._mutation_guard(operation) if self._mutation_guard else operation()

    def set_denied_document_ids(self, document_ids) -> None:
        self._denied_document_ids = {str(document_id) for document_id in document_ids}

    def set_query_authorization(self, manifests, snapshot) -> None:
        self._query_manifest_store = manifests
        self._query_manifest_snapshot = snapshot

    def revalidate_query_authorization(self) -> None:
        manifests = getattr(self, "_query_manifest_store", None)
        initial = getattr(self, "_query_manifest_snapshot", None)
        if manifests is None or initial is None:
            return
        current = manifests.read_snapshot()
        expected_digest = current.manifest.get("tombstone_set_digest")
        if not isinstance(expected_digest, str) or not expected_digest:
            raise RuntimeError("manifest tombstone digest is missing")
        if (
            current.manifest.get("tombstone_epoch") != initial.manifest.get("tombstone_epoch")
            or expected_digest != initial.manifest.get("tombstone_set_digest")
            or not manifests.revalidate(initial)
        ):
            raise RuntimeError("manifest changed during query selection")
        controls = manifests.tombstone_controls(current.manifest)
        self.verify_tombstone_control_points(controls, expected_digest=expected_digest)

    def set_active_vector_generations(self, generations: dict[str, int]) -> None:
        self._active_vector_generations = {str(key): int(value) for key, value in generations.items()}

    def capture_collection_baseline(self) -> None:
        """Record pre-existing ids so stale cleanup cannot delete newer attempts."""
        self._collection_baseline_records = self._scroll_point_records(include_control_points=True)

    def set_active_graph_selectors(self, selectors: dict[str, dict]) -> None:
        self._active_graph_selectors = {
            str(document_id): {
                "document_generation": int(selector["document_generation"]),
                "document_attempt_id": str(selector["document_attempt_id"]),
            }
            for document_id, selector in selectors.items()
        }

    def active_graph_filter(self) -> Filter:
        branches: list[Filter] = []
        for document_id, selector in sorted(self._active_graph_selectors.items()):
            branches.append(Filter(must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="document_generation", match=MatchValue(value=selector["document_generation"])),
                FieldCondition(key="document_attempt_id", match=MatchValue(value=selector["document_attempt_id"])),
                FieldCondition(key="graph_point", match=MatchValue(value=True)),
            ]))
        must: list[Condition] = [Filter(should=branches)] if branches else []
        return Filter(
            must=must,
            must_not=[
                FieldCondition(key="graph_control_point", match=MatchValue(value="document")),
                FieldCondition(key="graph_control_point", match=MatchValue(value="tombstone")),
                *[
                    FieldCondition(key="document_id", match=MatchValue(value=document_id))
                    for document_id in sorted(self._denied_document_ids)
                ],
            ],
        )

    def scroll_active_graph_points(self) -> list[tuple[str | int, dict]]:
        return self._scroll_point_records(self.active_graph_filter())

    # ========================================================
    # CREATE COLLECTION
    # Buat collection jika belum ada
    # ========================================================
    def create_collection_if_not_exists(self, vector_size: int | None = None):
        if not self.collection_exists():
            self._mutate(lambda: self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size or EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            ))
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
        self._mutate(lambda: create_index(
            collection_name=self.collection_name,
            field_name="document_id",
            field_schema=PayloadSchemaType.KEYWORD,
        ))

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
        offset = None
        seen_offsets = set()
        while True:
            points, next_offset = scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        IsEmptyCondition(
                            is_empty=PayloadField(key="document_id"),
                        )
                    ]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if points is None:
                raise RuntimeError("Qdrant legacy scan returned no page")
            for point in points:
                payload = point.payload or {}
                if payload.get("graph_control_point"):
                    continue
                if not isinstance(payload.get("document_id"), str) or not payload["document_id"].strip():
                    return True
            if next_offset is None:
                return False
            marker = str(next_offset)
            if marker in seen_offsets:
                raise RuntimeError("Qdrant legacy scan returned a repeated offset")
            seen_offsets.add(marker)
            offset = next_offset

    def delete_document(self, document_id: str) -> None:
        self._mutate(lambda: self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._document_filter(document_id),
            wait=True,
        ))

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
        if payload.get("document_generation") is not None:
            normalized["document_generation"] = payload["document_generation"]
        if payload.get("document_attempt_id") is not None:
            normalized["document_attempt_id"] = payload["document_attempt_id"]
        if payload.get("vector_point") is not None:
            normalized["vector_point"] = payload["vector_point"]
        if payload.get("graph_point") is not None:
            normalized["graph_point"] = payload["graph_point"]
        if payload.get("chunk_uid") is not None:
            normalized["chunk_uid"] = payload["chunk_uid"]
        elif payload.get("document_id") is not None:
            normalized["chunk_uid"] = build_chunk_uid(payload["document_id"], chunk_id)
        if payload.get("context_only"):
            normalized["context_only"] = True
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

        generation = int(chunk.get("document_generation", 1))
        if self._graph_claim and document_id:
            generation = int(self._graph_claim["document_generation"])
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
            "vector_point": True,
            "graph_point": False,
            "document_generation": generation,
        }
        if document_id:
            payload["document_id"] = document_id
            payload["chunk_uid"] = chunk_uid
        if self._graph_claim and document_id:
            source_point_id = point_id
            point_id = str(uuid5(
                NAMESPACE_URL,
                f"ingest-point:{self.collection_name}:{document_id}:{self._graph_claim['document_generation']}:{self._graph_claim['pending_attempt_id']}:{chunk_uid}",
            ))
            payload.update({
                "source_point_id": source_point_id,
                "source_fingerprint": self._graph_claim["source_fingerprint"],
                "document_attempt_id": self._graph_claim["pending_attempt_id"],
                "document_fence_token": self._graph_claim["document_fence_token"],
                "collection_fence_token": self._graph_claim["collection_fence_token"],
                "collection_attempt_id": self._graph_claim.get("collection_attempt_id"),
            })
        if chunk.get("context_only"):
            payload["context_only"] = True
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

        self._last_graph_points = [(str(point.id), dict(point.payload or {})) for point in points]

        total_batches = (len(points) + batch_size - 1) // batch_size
        for batch_number, start in enumerate(range(0, len(points), batch_size), start=1):
            batch = points[start:start + batch_size]
            if total_batches > 1:
                print(f"⬆️ Upload batch {batch_number}/{total_batches}: {len(batch)} points")
            self._mutate(lambda: self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            ))
        print(f"✅ Berhasil upload {len(points)} points ke Qdrant ({total_batches} batch)")
        return [point.id for point in points]

    def write_document_control_point(self, claim: dict, vector_size: int) -> str:
        if not self._graph_claim or self._graph_claim["pending_attempt_id"] != claim["pending_attempt_id"]:
            raise RuntimeError("graph claim is not attached to Qdrant")
        from graph.persistent import canonical_json_bytes

        items = [
            {"point_id": point_id, "payload": payload}
            for point_id, payload in sorted(self._last_graph_points, key=lambda item: item[0])
        ]
        point_set_digest = hashlib.sha256(canonical_json_bytes(items)).hexdigest()
        control_id = str(uuid5(
            NAMESPACE_URL,
            f"graph-control:document:{self.collection_name}:{claim['document_id']}:{claim['document_generation']}:{claim['pending_attempt_id']}",
        ))
        payload = {
            "graph_control_point": "document",
            "graph_point": True,
            "document_id": claim["document_id"],
            "document_complete": True,
            "document_generation": claim["document_generation"],
            "source_fingerprint": claim["source_fingerprint"],
            "document_attempt_id": claim["pending_attempt_id"],
            "document_fence_token": claim["document_fence_token"],
            "collection_fence_token": claim["collection_fence_token"],
            "collection_attempt_id": claim.get("collection_attempt_id"),
            "point_count": len(items),
            "point_set_digest": point_set_digest,
        }
        self._last_control_payload = payload
        self._last_control_id = control_id
        self._mutate(lambda: self.client.upsert(
            collection_name=self.collection_name,
            points=[PointStruct(id=control_id, vector=[0.0] * int(vector_size), payload=payload)],
        ))
        return control_id

    def verify_document_control_point(self, control_id: str) -> None:
        retrieve = getattr(self.client, "retrieve", None)
        if retrieve is None:
            raise RuntimeError("Qdrant cannot read back the document control point")
        points = retrieve(
            collection_name=self.collection_name,
            ids=[control_id],
            with_payload=True,
            with_vectors=False,
        )
        if len(points) != 1 or (points[0].payload or {}) != self._last_control_payload:
            raise RuntimeError("document control point proof mismatch")
        if not self._graph_claim:
            raise RuntimeError("document claim is missing for control proof")
        from graph.persistent import canonical_json_bytes

        claim = self._graph_claim
        attempt_filter = Filter(must=[
            FieldCondition(key="document_id", match=MatchValue(value=claim["document_id"])),
            FieldCondition(key="document_generation", match=MatchValue(value=claim["document_generation"])),
            FieldCondition(key="document_attempt_id", match=MatchValue(value=claim["pending_attempt_id"])),
        ])
        actual = [
            {"point_id": str(point_id), "payload": payload}
            for point_id, payload in sorted(self._scroll_point_records(attempt_filter), key=lambda item: str(item[0]))
        ]
        actual_digest = hashlib.sha256(canonical_json_bytes(actual)).hexdigest()
        expected = self._last_control_payload
        for item in actual:
            payload = item["payload"]
            if (
                payload.get("document_id") != claim["document_id"]
                or payload.get("document_generation") != claim["document_generation"]
                or payload.get("document_attempt_id") != claim["pending_attempt_id"]
                or payload.get("source_fingerprint") != claim["source_fingerprint"]
                or payload.get("document_fence_token") != claim["document_fence_token"]
                or payload.get("collection_fence_token") != claim["collection_fence_token"]
                or payload.get("collection_attempt_id") != claim.get("collection_attempt_id")
                or not payload.get("vector_point")
                or payload.get("graph_point")
            ):
                raise RuntimeError("document point provenance proof mismatch")
        if len(actual) != expected["point_count"] or actual_digest != expected["point_set_digest"]:
            raise RuntimeError("document point-set proof mismatch")

    def verify_graph_claim_current(self, claim: dict) -> None:
        if not self._graph_claim or self._graph_claim["pending_attempt_id"] != claim["pending_attempt_id"]:
            raise RuntimeError("graph claim is not attached to Qdrant")
        if not getattr(self, "_last_control_id", None):
            raise RuntimeError("document control proof is missing")
        self.verify_document_control_point(self._last_control_id)

    def write_tombstone_control_points(
        self,
        entries: list[dict],
        epoch: int,
        operation_id: str,
        fence_token: int,
        vector_size: int,
        attempt_id: str | None = None,
    ) -> list[dict]:
        controls = []
        for entry in sorted(entries, key=lambda item: str(item.get("document_id"))):
            document_id = str(entry["document_id"])
            control_id = str(uuid5(NAMESPACE_URL, f"graph-control:tombstone:{self.collection_name}:{document_id}"))
            payload = {
                "graph_control_point": "tombstone",
                "graph_point": True,
                "graph_tombstoned": True,
                "tombstone_complete": True,
                "document_id": document_id,
                "document_generation": entry.get("document_generation"),
                "tombstone_epoch": int(epoch),
                "tombstone_operation_id": operation_id,
                "tombstone_attempt_id": entry.get("tombstone_attempt_id"),
                "tombstone_fence_token": int(fence_token),
                "collection_fence_token": int(fence_token),
                "collection_attempt_id": attempt_id,
            }
            self._mutate(lambda control_id=control_id, payload=payload: self.client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(id=control_id, vector=[0.0] * int(vector_size), payload=payload)],
            ))
            controls.append({"point_id": control_id, "payload": payload})
        self._tombstone_controls = controls
        return controls

    def verify_tombstone_control_points(
        self,
        controls: list[dict],
        expected_digest: str | None = None,
        allow_stale_control_ids: set[str] | None = None,
    ) -> None:
        from graph.persistent import canonical_json_bytes

        if not isinstance(expected_digest, str) or not expected_digest:
            raise RuntimeError("tombstone control proof requires a committed digest")
        expected = sorted(controls, key=lambda item: str(item["point_id"]))
        actual = self._enumerate_tombstone_controls()
        expected_ids = {str(item["point_id"]) for item in expected}
        allowed_stale = {str(point_id) for point_id in (allow_stale_control_ids or set())}
        actual_expected = [item for item in actual if item["point_id"] in expected_ids]
        actual_stale = {item["point_id"] for item in actual if item["point_id"] not in expected_ids}
        if actual_stale - allowed_stale or actual_expected != expected:
            raise RuntimeError("tombstone control point proof mismatch")
        digest = hashlib.sha256(canonical_json_bytes(actual_expected)).hexdigest()
        if expected_digest is not None and digest != expected_digest:
            raise RuntimeError("tombstone control point digest mismatch")

    def verify_collection_tombstone_proof(self, manifests) -> None:
        snapshot = manifests.read_snapshot()
        controls = manifests.tombstone_controls(snapshot.manifest)
        self.verify_tombstone_control_points(
            controls,
            expected_digest=manifests.tombstone_proof_digest(snapshot.manifest),
        )

    def _enumerate_tombstone_controls(self) -> list[dict]:
        controls = [
            {"point_id": str(point_id), "payload": payload}
            for point_id, payload in self._scroll_point_records(
                Filter(must=[FieldCondition(key="graph_control_point", match=MatchValue(value="tombstone"))]),
                include_control_points=True,
            )
        ]
        return sorted(controls, key=lambda item: item["point_id"])

    def finalize_replace_collection(
        self,
        keep_point_ids: list,
        claim: dict | None = None,
        keep_control_ids: set[str] | None = None,
        remove_control_ids: set[str] | None = None,
    ) -> None:
        """Remove pre-existing points after a replacement upload has completed."""
        keep = {str(point_id) for point_id in keep_point_ids}
        remove_controls = {str(point_id) for point_id in (remove_control_ids or set())}
        baseline = getattr(self, "_collection_baseline_records", None)
        stale_tombstone_records = []
        if baseline is not None:
            records = baseline
            stale_ids = [
                point_id for point_id, payload in records
                if str(point_id) not in keep
                and not payload.get("graph_control_point")
            ]
            stale_ids.extend(
                point_id for point_id, payload in records
                if str(point_id) in remove_controls and payload.get("graph_control_point") == "tombstone"
            )
            stale_tombstone_records = [
                (point_id, payload)
                for point_id, payload in records
                if str(point_id) in remove_controls and payload.get("graph_control_point") == "tombstone"
            ]
            stale_ids = [point_id for point_id in stale_ids if not any(point_id == item[0] for item in stale_tombstone_records)]
        elif claim:
            records = self._scroll_point_records(include_control_points=keep_control_ids is not None)
            stale_ids = [
                point_id for point_id, payload in records
                if str(point_id) not in keep
                and (
                    not payload.get("graph_control_point")
                    or keep_control_ids is None
                    or str(point_id) not in keep_control_ids
                )
            ]
        else:
            stale_ids = [point_id for point_id in self._scroll_point_ids() if str(point_id) not in keep]

        if stale_ids:
            stale_ids = list(dict.fromkeys(stale_ids))
            self._mutate(lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=stale_ids),
                wait=True,
            ))
        if stale_tombstone_records:
            def delete_stale_tombstones():
                for point_id, payload in stale_tombstone_records:
                    conditions: list[Condition] = [HasIdCondition(has_id=[str(point_id)])]
                    for key in (
                        "graph_control_point",
                        "document_id",
                        "document_generation",
                        "tombstone_epoch",
                        "tombstone_operation_id",
                        "tombstone_attempt_id",
                        "tombstone_fence_token",
                        "collection_fence_token",
                        "collection_attempt_id",
                    ):
                        if payload.get(key) is not None:
                            conditions.append(FieldCondition(key=key, match=MatchValue(value=payload[key])))
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=Filter(must=conditions),
                        wait=True,
                    )

            self._mutate(delete_stale_tombstones)
        print(f"✅ Replace-collection selesai; {len(stale_ids)} legacy points dihapus")

    def finalize_replace_document(self, document_id: str, keep_point_ids: list, claim: dict | None = None) -> None:
        """Remove stale points for one document after its replacement upload completes."""
        keep = {str(point_id) for point_id in keep_point_ids}
        if claim:
            stale_ids = [
                point_id
                for point_id, payload in self._scroll_point_records(self._document_filter(document_id))
                if str(point_id) not in keep
                and int(payload.get("document_generation", 0)) <= int(claim["document_generation"])
            ]
        else:
            stale_ids = [
                point_id
                for point_id in self._scroll_point_ids(self._document_filter(document_id))
                if str(point_id) not in keep
            ]

        if stale_ids:
            self._mutate(lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=stale_ids),
                wait=True,
            ))
        print(f"✅ Replace-document selesai; {len(stale_ids)} stale points dihapus")

    def _scroll_point_ids(self, scroll_filter: Filter | None = None) -> list:
        return [point_id for point_id, _ in self._scroll_point_records(scroll_filter)]

    def _scroll_point_records(
        self,
        scroll_filter: Filter | None = None,
        *,
        include_control_points: bool = False,
    ) -> list[tuple[str | int, dict]]:
        scroll_offset = None
        seen_offsets = set()
        points_with_payload = []
        while True:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=256,
                offset=scroll_offset,
                with_payload=True,
                with_vectors=False,
            )
            if points is None:
                raise RuntimeError("Qdrant point scan returned no page")
            points_with_payload.extend(
                (point.id, point.payload or {}) for point in points
                if include_control_points or not (point.payload or {}).get("graph_control_point")
            )
            if next_offset is None:
                break
            marker = str(next_offset)
            if marker in seen_offsets:
                raise RuntimeError("Qdrant point scan returned a repeated offset")
            seen_offsets.add(marker)
            scroll_offset = next_offset
        return points_with_payload

    # ========================================================
    # SEARCH RAW RESULTS
    # Cari chunk paling relevan dari query vector
    # ========================================================
    def search(self, query_vector: list, limit: int = 5):
        denied: list[Condition] = [
            FieldCondition(key="document_id", match=MatchValue(value=document_id))
            for document_id in sorted(self._denied_document_ids)
        ]
        must: list[Condition] = [IsEmptyCondition(is_empty=PayloadField(key="graph_control_point"))]
        must_not: list[Condition] = denied + [FieldCondition(key="graph_point", match=MatchValue(value=True))]
        if self._active_vector_generations is not None and not self._active_vector_generations:
            return []
        if self._active_vector_generations is not None:
            active_documents: list[Filter] = []
            for document_id, generation in sorted(self._active_vector_generations.items()):
                conditions: list[Condition] = [
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    FieldCondition(key="document_generation", match=MatchValue(value=generation)),
                    FieldCondition(key="vector_point", match=MatchValue(value=True)),
                ]
                active_documents.append(Filter(must=conditions))
            must.append(Filter(should=active_documents))
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=Filter(must=must, must_not=must_not),
            with_payload=True,
            with_vectors=False,
        )
        if self._active_vector_generations is not None:
            filtered = []
            for result in results:
                payload = result.payload or {}
                document_id = payload.get("document_id")
                if not isinstance(document_id, str):
                    continue
                if payload.get("document_generation") != self._active_vector_generations.get(document_id):
                    continue
                if not payload.get("vector_point") or payload.get("graph_point"):
                    continue
                filtered.append(result)
            results = filtered
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

    def scroll_document_chunks(self, document_id: str | None = None, limit: int = 256, include_vectors: bool = False) -> list[dict]:
        """Read payloads for graph backfill without fetching vectors."""
        scroll = getattr(self.client, "scroll", None)
        if scroll is None:
            raise RuntimeError("Qdrant client cannot scroll payloads for backfill")
        scroll_filter = self._document_filter(document_id) if document_id else None
        offset = None
        seen_offsets = set()
        chunks = []
        while True:
            points, offset = scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=include_vectors,
            )
            if points is None:
                raise RuntimeError("Qdrant backfill scan returned no page")
            for point in points:
                payload = point.payload or {}
                if payload.get("graph_control_point"):
                    continue
                if not payload.get("document_id"):
                    raise ValueError("legacy point without document_id cannot be backfilled")
                chunk = self._normalize_chunk_payload(payload, fallback_chunk_id=point.id)
                if include_vectors and getattr(point, "vector", None) is not None:
                    chunk["_embedding"] = point.vector
                chunks.append(chunk)
            if offset is None:
                break
            marker = str(offset)
            if marker in seen_offsets:
                raise RuntimeError("Qdrant backfill scan returned a repeated offset")
            seen_offsets.add(marker)
        return chunks

    # Explicit alias keeps the backfill seam discoverable without changing the
    # existing search/upsert API.
    list_document_chunks = scroll_document_chunks

    def expand_parent_context(self, chunks: list[dict[str, Any]], max_depth: int = 2) -> list[dict[str, Any]]:
        """Attach bounded hierarchy parents without adding them to the graph input."""
        retrieve = getattr(self.client, "retrieve", None)
        max_depth = max(0, int(max_depth))
        if retrieve is None or max_depth == 0:
            return chunks

        def parent_point_id(chunk: dict[str, Any]) -> str | None:
            hierarchy = chunk.get("hierarchy") or {}
            parent_point_id = hierarchy.get("parent_point_id")
            if parent_point_id is not None:
                return str(parent_point_id)
            document_id = chunk.get("document_id")
            parent_chunk_id = hierarchy.get("parent_chunk_id")
            if isinstance(document_id, str) and parent_chunk_id is not None:
                return stable_point_id(document_id, parent_chunk_id)
            parent_uid = hierarchy.get("parent_chunk_uid")
            if parent_uid is not None:
                prefix = f"{document_id}:chunk:" if isinstance(document_id, str) else None
                if isinstance(document_id, str) and prefix and str(parent_uid).startswith(prefix):
                    return stable_point_id(document_id, str(parent_uid)[len(prefix):])
                if ":" not in str(parent_uid):
                    return str(parent_uid)
            return None

        pending = {
            point_id
            for chunk in chunks
            if (point_id := parent_point_id(chunk)) is not None
        }
        parent_records: dict[str, dict[str, Any]] = {}
        failure_reason = None
        try:
            for _ in range(max_depth):
                pending -= set(parent_records)
                if not pending:
                    break
                results = retrieve(
                    collection_name=self.collection_name,
                    ids=sorted(pending),
                    with_payload=True,
                    with_vectors=False,
                )
                fetched = {}
                for result in results or []:
                    point_id = str(result.id)
                    fetched[point_id] = self._normalize_chunk_payload(
                        result.payload or {},
                        fallback_chunk_id=result.id,
                    )
                parent_records.update(fetched)
                pending = {
                    point_id
                    for record in fetched.values()
                    if (point_id := parent_point_id(record)) is not None
                }
        except (ApiException, ResponseHandlingException, UnexpectedResponse) as exc:
            failure_reason = type(exc).__name__
            print(f"⚠️ Parent context expansion incomplete: {failure_reason}")

        for chunk in chunks:
            context = []
            point_id = parent_point_id(chunk)
            initial_point_id = point_id
            seen = set()
            for depth in range(1, max_depth + 1):
                if point_id is None or point_id in seen:
                    break
                seen.add(point_id)
                parent = parent_records.get(point_id)
                if parent is None:
                    break
                context.append({
                    "chunk_id": parent.get("chunk_uid", parent.get("chunk_id")),
                    "local_chunk_id": parent.get("chunk_id"),
                    "level": parent.get("level", "paragraph"),
                    "text": parent.get("text", ""),
                    "hierarchy": parent.get("hierarchy", {}),
                    "source": parent.get("source", "unknown"),
                    "context_only": bool(parent.get("context_only")),
                    "depth": depth,
                    "reason": "hierarchy_parent",
                })
                point_id = parent_point_id(parent)
            chunk["parent_context"] = context
            if failure_reason:
                status = "partial" if context else "unavailable"
            elif initial_point_id is None:
                status = "not_present"
            elif point_id is None:
                status = "available"
            else:
                status = "partial"
            chunk["parent_context_status"] = {
                "status": status,
                "requested_depth": max_depth,
                "added_parent_count": len(context),
            }
            if failure_reason:
                chunk["parent_context_status"]["reason"] = failure_reason
        return chunks
