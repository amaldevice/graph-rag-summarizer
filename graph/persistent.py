"""Small, deterministic document-graph artifact and manifest contract.

The object store is deliberately injected.  Production uses the configured S3
compatible backend; tests use :class:`InMemoryObjectStore` and never need a
network service.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import networkx as nx


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785-compatible UTF-8 bytes for the supported JSON values."""
    return _jcs_encode(_canonical_value(value)).encode("utf-8")


def _jcs_encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite numbers are not valid canonical JSON")
        if value == 0:
            return "0"
        text = repr(value).lower()
        if "e" not in text:
            return text
        mantissa, exponent = text.split("e")
        exponent_value = int(exponent)
        if -6 <= exponent_value < 21:
            sign = "-" if mantissa.startswith("-") else ""
            unsigned = mantissa.lstrip("-")
            digits = unsigned.replace(".", "")
            dot = unsigned.find(".")
            decimal_position = (dot if dot >= 0 else len(unsigned)) + exponent_value
            if decimal_position <= 0:
                return f"{sign}0.{('0' * -decimal_position) + digits}"
            if decimal_position >= len(digits):
                return f"{sign}{digits}{'0' * (decimal_position - len(digits))}"
            return f"{sign}{digits[:decimal_position]}.{digits[decimal_position:]}"
        sign = "+" if exponent_value >= 0 else "-"
        return f"{mantissa}e{sign}{abs(exponent_value)}"
    if isinstance(value, list):
        return "[" + ",".join(_jcs_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: str(item[0]).encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(f"{_jcs_encode(str(key))}:{_jcs_encode(item)}" for key, item in items) + "}"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite numbers are not valid canonical JSON")
        return int(value) if value.is_integer() else value
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _chunk_sort_key(chunk: dict) -> tuple[int, str]:
    try:
        chunk_id = int(chunk.get("chunk_id", 0))
    except (TypeError, ValueError):
        chunk_id = 0
    return chunk_id, str(chunk.get("chunk_uid", ""))


def _image_urls(chunk: dict) -> list[str]:
    urls = chunk.get("image_urls")
    if urls is None and chunk.get("image_url"):
        urls = [chunk["image_url"]]
    return sorted(str(url) for url in (urls or []) if url)


def source_fingerprint(chunks: list[dict], document_id: str) -> str:
    """Hash only stable source fields; never hash vectors or transient metadata."""
    descriptor = {
        "document_id": document_id,
        "chunks": [
            {
                "chunk_uid": chunk.get("chunk_uid"),
                "chunk_id": chunk.get("chunk_id"),
                "text": chunk.get("text", ""),
                "hierarchy": chunk.get("hierarchy") or {},
                "layout": chunk.get("layout") or {},
                "page_no": chunk.get("page_no", chunk.get("page")),
                "image_urls": _image_urls(chunk),
            }
            for chunk in sorted(chunks, key=_chunk_sort_key)
        ],
    }
    return _digest(canonical_json_bytes(descriptor))


def _graph_node_record(node: str, attrs: dict) -> dict:
    return {"id": str(node), "attrs": _json_safe(dict(sorted(attrs.items())))}


def serialize_graph(
    graph: nx.Graph,
    chunks: list[dict],
    document_id: str,
    generation: int,
    raw_evidence: list[dict] | None = None,
    diagnostics: dict | None = None,
) -> bytes:
    """Serialize graph structure without copying full chunk text."""
    nodes = sorted(
        (_graph_node_record(node, graph.nodes[node]) for node in graph.nodes),
        key=lambda item: item["id"],
    )
    edges = []
    for first, second, attrs in graph.edges(data=True):
        left, right = sorted((str(first), str(second)))
        edges.append({"source": left, "target": right, "attrs": _json_safe(dict(sorted(attrs.items())))})
    edges.sort(key=lambda item: (item["source"], item["target"]))
    chunk_refs = []
    for chunk in sorted(chunks, key=_chunk_sort_key):
        chunk_refs.append({
            "chunk_id": chunk.get("chunk_id"),
            "chunk_uid": chunk.get("chunk_uid"),
            "document_id": chunk.get("document_id", document_id),
            "level": chunk.get("level", "paragraph"),
            "hierarchy": chunk.get("hierarchy") or {},
            "layout": chunk.get("layout") or {},
            "page_no": chunk.get("page_no", chunk.get("page")),
            "source": chunk.get("source", "unknown"),
        })
    payload = {
        "schema_version": 1,
        "document_id": document_id,
        "document_generation": int(generation),
        "source_fingerprint": source_fingerprint(chunks, document_id),
        "chunks": chunk_refs,
        "nodes": nodes,
        "edges": edges,
        "raw_evidence": _json_safe(raw_evidence or []),
        "diagnostics": _json_safe(diagnostics or {}),
        "graph_metadata": _json_safe(dict(graph.graph)),
    }
    return canonical_json_bytes(payload)


def deserialize_graph(data: bytes | str) -> dict:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return json.loads(data.decode("utf-8"))


class InMemoryObjectStore:
    """S3-like store used by deterministic tests and local dry runs."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, dict[str, str], str]] = {}
        self.fencing_enforced = True
        self.supports_conditional_cas = True
        self._lock = threading.RLock()

    def put(self, key: str, data: bytes, *, if_none_match: bool = False, if_match: str | None = None, metadata=None) -> str:
        with self._lock:
            current = self.objects.get(key)
            if if_none_match and current is not None:
                raise FileExistsError(key)
            if if_match is not None and (current is None or current[2] != if_match):
                raise RuntimeError("object precondition failed")
            current_fence = int((current[1] if current else {}).get("fence_token", 0))
            requested_fence = int((metadata or {}).get("fence_token", 0))
            if requested_fence < current_fence:
                raise RuntimeError("object fence token is stale")
            etag = _digest(data)
            self.objects[key] = (bytes(data), dict(metadata or {}), etag)
            return etag

    def get(self, key: str) -> tuple[bytes, dict[str, str], str]:
        with self._lock:
            if key not in self.objects:
                raise FileNotFoundError(key)
            return self.objects[key]

    def head(self, key: str) -> tuple[dict[str, str], str]:
        data, metadata, etag = self.get(key)
        del data
        return metadata, etag

    def delete(self, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)


class S3ObjectStore:
    """Adapter over the existing R2/MinIO handler without changing image APIs."""

    def __init__(self, handler):
        self.handler = handler
        self.client = handler.client
        self.bucket = handler.bucket_name
        self.fencing_enforced = False
        self.supports_conditional_cas = True

    def put(self, key: str, data: bytes, *, if_none_match: bool = False, if_match: str | None = None, metadata=None) -> str:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": data, "Metadata": metadata or {}}
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        if if_match:
            kwargs["IfMatch"] = if_match
        response = self.client.put_object(**kwargs)
        return str(response.get("ETag", "")).strip('"') or _digest(data)

    def get(self, key: str) -> tuple[bytes, dict[str, str], str]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if "404" in str(exc) or "NoSuchKey" in str(exc) or "Not Found" in str(exc):
                raise FileNotFoundError(key) from exc
            raise
        body = response["Body"].read()
        return body, response.get("Metadata", {}), str(response.get("ETag", "")).strip('"') or _digest(body)

    def head(self, key: str) -> tuple[dict[str, str], str]:
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        return response.get("Metadata", {}), str(response.get("ETag", "")).strip('"')

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class GraphArtifactStore:
    def __init__(self, object_store, collection: str):
        self.object_store = object_store
        self.collection = collection

    def key(self, document_id: str, version: int) -> str:
        return str(PurePosixPath("graphs", self.collection, document_id, f"v{int(version)}", "graph.json.gz"))

    def write(self, claim: dict, canonical_bytes: bytes) -> tuple[str, str]:
        if not isinstance(canonical_bytes, bytes):
            canonical_bytes = canonical_bytes.encode("utf-8")
        digest = _digest(canonical_bytes)
        key = self.key(claim["document_id"], claim["pending_version"])
        compressed = gzip.compress(canonical_bytes, compresslevel=6, mtime=0)
        backend = claim.get("pending_backend") or claim.get("backend") or {}
        metadata = {
            "artifact_digest": digest,
            "document_generation": str(claim["document_generation"]),
            "source_fingerprint": str(claim["source_fingerprint"]),
            "operation_id": str(claim.get("operation_id", "")),
            "pending_attempt_id": str(claim.get("pending_attempt_id", "")),
            "build_attempt_id": str(claim.get("build_attempt_id", "")),
            "backend_kind": str(backend.get("kind", "")),
            "backend_namespace": str(backend.get("namespace", "")),
        }
        try:
            self.object_store.put(key, compressed, if_none_match=True, metadata=metadata)
        except FileExistsError:
            existing, existing_metadata, _ = self.object_store.get(key)
            if (
                gzip.decompress(existing) != canonical_bytes
                or existing_metadata.get("artifact_digest") != digest
                or existing_metadata.get("document_generation") != str(claim["document_generation"])
                or existing_metadata.get("backend_kind") != str(backend.get("kind", ""))
                or existing_metadata.get("backend_namespace") != str(backend.get("namespace", ""))
            ):
                raise ValueError("immutable graph artifact key contains different bytes")
        return key, digest

    def read(self, key: str, expected_digest: str | None = None, expected_backend: dict | None = None, expected_generation: int | None = None, expected_source_fingerprint: str | None = None) -> bytes:
        compressed, metadata, _ = self.object_store.get(key)
        data = gzip.decompress(compressed)
        digest = _digest(data)
        if expected_digest and digest != expected_digest:
            raise ValueError("graph artifact digest mismatch")
        if not metadata.get("artifact_digest"):
            raise ValueError("graph artifact metadata is missing digest")
        if metadata["artifact_digest"] != digest:
            raise ValueError("graph artifact metadata mismatch")
        if expected_generation is not None and metadata.get("document_generation") != str(expected_generation):
            raise ValueError("graph artifact generation mismatch")
        if expected_source_fingerprint is not None and metadata.get("source_fingerprint") != str(expected_source_fingerprint):
            raise ValueError("graph artifact source fingerprint mismatch")
        if expected_backend and (
            not metadata.get("backend_kind")
            or metadata.get("backend_kind") != str(expected_backend.get("kind", ""))
            or metadata.get("backend_namespace") != str(expected_backend.get("namespace", ""))
        ):
            raise ValueError("graph artifact backend mismatch")
        return data


@dataclass(frozen=True)
class ManifestSnapshot:
    data: bytes
    etag: str | None
    manifest_revision: int
    digest: str
    manifest: dict
    fence_token: int | None = None


class ManifestStore:
    """Versioned manifest with optimistic CAS and document-scoped claims."""

    def __init__(self, object_store, collection: str, backend: dict | None = None):
        self.object_store = object_store
        self.collection = collection
        self.backend = backend or {"kind": "unknown", "namespace": ""}
        self._lock = threading.RLock()
        self._fences = FenceCoordinator()
        self.manifest_key = str(PurePosixPath("graphs", collection, "manifest.json"))
        self.lock_key = str(PurePosixPath("locks", f"{collection}.json"))

    def _default(self) -> dict:
        return {
            "schema_version": 1,
            "collection": self.collection,
            "manifest_revision": 0,
            "tombstone_epoch": 0,
            "collection_fence_token": 0,
            "collection_operation_id": None,
            "collection_attempt_id": None,
            "manifest_backend": self.backend,
            "tombstone_set_digest": _digest(canonical_json_bytes([])),
            "pending_tombstone_set_digest": None,
            "documents": {},
        }

    def _read(self) -> tuple[dict, str | None]:
        manifest, _, etag = self._read_raw()
        return manifest, etag

    def _read_raw(self) -> tuple[dict, bytes, str | None]:
        try:
            data, _, etag = self.object_store.get(self.manifest_key)
        except FileNotFoundError:
            data = canonical_json_bytes(self._default())
            return self._default(), data, None
        manifest = json.loads(data.decode("utf-8"))
        if manifest.get("manifest_backend") != self.backend:
            raise ValueError("manifest backend namespace mismatch")
        return manifest, data, etag

    def read_snapshot(self) -> ManifestSnapshot:
        with self._lock:
            manifest, data, etag = self._read_raw()
            return ManifestSnapshot(
                data,
                etag,
                int(manifest.get("manifest_revision", 0)),
                _digest(data),
                manifest,
                self._current_fence_token(),
            )

    def revalidate(self, snapshot: ManifestSnapshot) -> bool:
        current = self.read_snapshot()
        return (
            current.digest == snapshot.digest
            and current.etag == snapshot.etag
            and current.fence_token == snapshot.fence_token
        )

    def _current_fence_token(self) -> int | None:
        try:
            data, _, _ = self.object_store.get(self.lock_key)
        except FileNotFoundError:
            return None
        return int(json.loads(data.decode("utf-8")).get("fence_token", 0))

    def _acquire_fence(self) -> int:
        current = self._current_fence_token()
        next_token = int(current or 0) + 1
        lock = {"collection": self.collection, "fence_token": next_token, "updated_at": _now()}
        data = canonical_json_bytes(lock)
        try:
            _, _, etag = self.object_store.get(self.lock_key)
        except FileNotFoundError:
            etag = None
        kwargs = {
            "metadata": {"fence_token": str(next_token)},
        }
        if etag is None:
            kwargs["if_none_match"] = True
        else:
            kwargs["if_match"] = etag
        self.object_store.put(self.lock_key, data, **kwargs)
        return next_token

    def _write(self, manifest: dict, etag: str | None) -> dict:
        manifest = dict(manifest)
        manifest["manifest_revision"] = int(manifest.get("manifest_revision", 0)) + 1
        data = canonical_json_bytes(manifest)
        fence_token = self._acquire_fence()
        if etag is None and not getattr(self.object_store, "fencing_enforced", False):
            try:
                self.object_store.get(self.manifest_key)
            except FileNotFoundError:
                pass
            else:
                raise RuntimeError("manifest backend cannot enforce durable fencing")
        kwargs = {"metadata": {
            "manifest_revision": str(manifest["manifest_revision"]),
            "fence_token": str(fence_token),
        }}
        if etag is None:
            kwargs["if_none_match"] = True
        else:
            kwargs["if_match"] = etag
        self.object_store.put(self.manifest_key, data, **kwargs)
        return manifest

    def get(self, document_id: str) -> dict | None:
        return self._read()[0].get("documents", {}).get(document_id)

    def entries(self) -> dict[str, dict]:
        return dict(self._read()[0].get("documents", {}))

    def assert_claim_current(self, claim: dict) -> None:
        with self._lock:
            current = self.get(claim["document_id"])
            if not self._claim_matches(current, claim):
                raise RuntimeError("stale graph claim cannot mutate Qdrant")
            scope = f"document:{self.collection}:{claim['document_id']}"
            self._fences.accept(scope, int(claim["document_fence_token"]))

    def mutate_claim(self, claim: dict, operation):
        with self._lock:
            current = self.get(claim["document_id"])
            if not self._claim_matches(current, claim):
                raise RuntimeError("stale graph claim cannot mutate Qdrant")
            scope = f"document:{self.collection}:{claim['document_id']}"
            self._fences.accept(scope, int(claim["document_fence_token"]))
            return self._fences.mutate(scope, int(claim["document_fence_token"]), operation)

    def mutate_collection(self, operation_id: str, fence_token: int, operation):
        with self._lock:
            manifest, _ = self._read()
            if (
                manifest.get("collection_operation_id") != operation_id
                or manifest.get("pending_tombstone_set_digest") not in {"pending", None}
                or int(manifest.get("collection_fence_token", 0)) != int(fence_token)
            ):
                raise RuntimeError("stale collection fence cannot mutate Qdrant")
            scope = f"collection:{self.collection}"
            self._fences.accept(scope, int(fence_token))
            return self._fences.mutate(scope, int(fence_token), operation)

    def reserve(self, document_id: str, operation_id: str, source_fingerprint_value: str, *, mode: str = "append") -> dict:
        with self._lock:
            manifest, etag = self._read()
            documents = dict(manifest.get("documents", {}))
            prior = documents.get(document_id)
            if mode == "append" and prior is not None:
                raise ValueError(f"document '{document_id}' is already tracked; use replace-document")
            if prior and prior.get("pending_operation_id") and prior["pending_operation_id"] != operation_id:
                raise RuntimeError("document has an active graph claim")
            generation = int(prior.get("document_generation", 0)) + 1 if prior else 1
            next_version = int(prior.get("next_version", 1)) if prior else 1
            ledger = list(prior.get("version_ledger", [])) if prior else []
            previous_pointer = None
            if prior and prior.get("active_artifact_key"):
                previous_pointer = {
                    "artifact_key": prior["active_artifact_key"],
                    "version": prior.get("active_version"),
                    "backend": prior.get("backend"),
                    "artifact_digest": prior.get("artifact_digest"),
                    "document_generation": prior.get("document_generation"),
                }
            claim = {
                "document_id": document_id,
                "document_generation": generation,
                "source_fingerprint": source_fingerprint_value,
                "artifact_digest": prior.get("artifact_digest") if prior else None,
                "pending_artifact_digest": None,
                "operation_id": operation_id,
                "pending_operation_id": operation_id,
                "pending_generation": generation,
                "pending_source_fingerprint": source_fingerprint_value,
                "pending_backend": self.backend,
                "pending_artifact_key": None,
                "pending_attempt_id": str(uuid.uuid4()),
                "document_attempt_id": prior.get("document_attempt_id") if prior else None,
                "next_version": next_version + 1,
                "pending_version": next_version,
                "active_version": prior.get("active_version") if prior else None,
                "active_artifact_key": prior.get("active_artifact_key") if prior else None,
                "build_attempt_id": str(uuid.uuid4()),
                "status": "pending",
                "backend": prior.get("backend") if prior else None,
                "previous_pointer": previous_pointer,
                "updated_at": _now(),
                "failure_reason": None,
                "tombstone_operation_id": None,
                "tombstone_attempt_id": None,
                "tombstone_fence_token": None,
                "document_fence_token": int(prior.get("document_fence_token", 0)) + 1 if prior else 1,
                "collection_fence_token": int(manifest.get("collection_fence_token", 0)),
                "version_ledger": ledger + [{
                    "version": next_version,
                    "artifact_key": None,
                    "artifact_digest": None,
                    "backend_authority": self.backend,
                    "source_fingerprint": source_fingerprint_value,
                    "operation_id": operation_id,
                    "document_generation": generation,
                    "attempt_id": None,
                    "fence_token": int(prior.get("document_fence_token", 0)) + 1 if prior else 1,
                    "fence_scope": "document",
                    "state": "reserved",
                    "reserved_at": _now(),
                    "updated_at": _now(),
                }],
            }
            documents[document_id] = claim
            claim["version_ledger"][-1]["attempt_id"] = claim["pending_attempt_id"]
            manifest["documents"] = documents
            return self._write(manifest, etag) and claim

    def _claim_matches(self, current: dict | None, claim: dict) -> bool:
        fields = (
            "operation_id",
            "document_generation",
            "source_fingerprint",
            "pending_operation_id",
            "pending_generation",
            "pending_source_fingerprint",
            "pending_version",
            "pending_attempt_id",
            "build_attempt_id",
            "collection_fence_token",
            "document_fence_token",
        )
        return bool(
            current
            and all(current.get(field) == claim.get(field) for field in fields)
        )

    def publish(self, claim: dict, artifact_key: str, artifact_digest: str) -> dict:
        with self._lock:
            manifest, etag = self._read()
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim):
                raise RuntimeError("stale graph claim cannot publish")
            previous = current.get("previous_pointer")
            prior_active_version = current.get("active_version")
            current = dict(current)
            current.update({
                "artifact_digest": artifact_digest,
                "pending_artifact_digest": None,
                "pending_artifact_key": None,
                "pending_backend": None,
                "active_version": claim["pending_version"],
                "active_artifact_key": artifact_key,
                "document_attempt_id": claim["pending_attempt_id"],
                "status": "available",
                "backend": self.backend,
                "previous_pointer": previous,
                "pending_operation_id": None,
                "pending_generation": None,
                "pending_source_fingerprint": None,
                "pending_version": None,
                "pending_attempt_id": None,
                "pending_backend": None,
                "pending_artifact_key": None,
                "pending_artifact_digest": None,
                "build_attempt_id": None,
                "updated_at": _now(),
                "failure_reason": None,
            })
            for item in current["version_ledger"]:
                if item["version"] == claim["pending_version"]:
                    item.update({"artifact_key": artifact_key, "artifact_digest": artifact_digest, "state": "published_available", "updated_at": _now()})
                elif item["version"] == prior_active_version and item.get("state") == "published_available":
                    item["state"] = "retired"
            manifest["documents"][claim["document_id"]] = current
            self._write(manifest, etag)
            return current

    def bind_artifact(self, claim: dict, artifact_key: str, artifact_digest: str) -> dict:
        """Record the pending immutable blob before the activation CAS."""
        with self._lock:
            manifest, etag = self._read()
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim):
                raise RuntimeError("stale graph claim cannot bind artifact")
            current = dict(current)
            current["pending_artifact_key"] = artifact_key
            current["pending_artifact_digest"] = artifact_digest
            manifest["documents"][claim["document_id"]] = current
            self._write(manifest, etag)
            return current

    def tombstone_documents(self, retained_document_ids: set[str], operation_id: str) -> dict:
        """Make omitted replace-collection documents non-discoverable."""
        with self._lock:
            manifest, etag = self._read()
            documents = dict(manifest.get("documents", {}))
            manifest["tombstone_epoch"] = int(manifest.get("tombstone_epoch", 0)) + 1
            for document_id, entry in documents.items():
                if document_id in retained_document_ids:
                    continue
                entry = dict(entry)
                if entry.get("active_artifact_key"):
                    entry["previous_pointer"] = {
                        "artifact_key": entry["active_artifact_key"],
                        "version": entry.get("active_version"),
                        "backend": entry.get("backend"),
                        "artifact_digest": entry.get("artifact_digest"),
                        "document_generation": entry.get("document_generation"),
                    }
                entry.update({
                    "status": "tombstoned",
                    "tombstone_operation_id": operation_id,
                    "tombstone_attempt_id": f"{operation_id}:{document_id}",
                    "tombstone_fence_token": int(manifest.get("collection_fence_token", 0)) + 1,
                    "active_version": None,
                    "active_artifact_key": None,
                    "artifact_digest": None,
                    "backend": None,
                    "pending_operation_id": None,
                    "pending_version": None,
                    "pending_attempt_id": None,
                    "pending_backend": None,
                    "pending_artifact_key": None,
                    "pending_artifact_digest": None,
                    "updated_at": _now(),
                    "failure_reason": "omitted by replace-collection",
                })
                documents[document_id] = entry
            manifest["documents"] = documents
            manifest["collection_fence_token"] = int(manifest.get("collection_fence_token", 0)) + 1
            manifest["collection_operation_id"] = operation_id
            manifest["collection_attempt_id"] = f"{operation_id}:tombstone"
            manifest["pending_tombstone_set_digest"] = "pending"
            tombstones = sorted({
                (document_id, entry.get("tombstone_attempt_id"))
                for document_id, entry in documents.items()
                if entry.get("status") == "tombstoned"
            })
            manifest["tombstone_set_digest"] = _digest(canonical_json_bytes(tombstones))
            self._write(manifest, etag)
            return manifest

    def commit_tombstone_proof(self, proofs: list[dict]) -> dict:
        with self._lock:
            manifest, etag = self._read()
            if manifest.get("pending_tombstone_set_digest") != "pending":
                raise RuntimeError("no pending tombstone proof")
            ordered = sorted(proofs, key=lambda item: str(item["point_id"]))
            expected_ids = {
                str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"graph-control:tombstone:{self.collection}:{document_id}",
                ))
                for document_id, entry in manifest.get("documents", {}).items()
                if entry.get("status") == "tombstoned"
            }
            if {str(item["point_id"]) for item in ordered} != expected_ids:
                raise RuntimeError("tombstone proof does not cover the committed deny set")
            digest = _digest(canonical_json_bytes(ordered))
            manifest["tombstone_set_digest"] = digest
            manifest["pending_tombstone_set_digest"] = None
            self._write(manifest, etag)
            return manifest

    def release_collection_fence(self, operation_id: str, fence_token: int) -> dict:
        with self._lock:
            manifest, etag = self._read()
            if (
                manifest.get("collection_operation_id") != operation_id
                or int(manifest.get("collection_fence_token", 0)) != int(fence_token)
            ):
                raise RuntimeError("stale collection fence cannot be released")
            manifest["collection_operation_id"] = None
            manifest["collection_attempt_id"] = None
            self._write(manifest, etag)
            return manifest

    def preflight(self, document_id: str) -> dict:
        """Fail closed for tombstones before compatibility fallback."""
        manifest, _ = self._read()
        entry = manifest.get("documents", {}).get(document_id)
        if manifest.get("pending_tombstone_set_digest") is not None:
            return {"allowed": False, "reason": "tombstone_proof_pending", "entry": entry}
        if entry and entry.get("status") == "tombstoned":
            return {"allowed": False, "reason": "tombstoned", "entry": entry}
        return {"allowed": True, "reason": "not_denied", "entry": entry}

    def fail(self, claim: dict, reason: str) -> dict:
        with self._lock:
            manifest, etag = self._read()
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim):
                raise RuntimeError("stale graph claim cannot fail")
            current = dict(current)
            current.update({
                "status": "partial" if current.get("active_artifact_key") else "unavailable",
                "pending_operation_id": None,
                "pending_generation": None,
                "pending_source_fingerprint": None,
                "pending_version": None,
                "pending_attempt_id": None,
                "pending_backend": None,
                "pending_artifact_key": None,
                "pending_artifact_digest": None,
                "build_attempt_id": None,
                "failure_reason": str(reason)[:500],
                "updated_at": _now(),
            })
            for item in current.get("version_ledger", []):
                if item.get("version") == claim.get("pending_version") and item.get("state") == "reserved":
                    item["state"] = "failed"
            manifest["documents"][claim["document_id"]] = current
            self._write(manifest, etag)
            return current


class FenceCoordinator:
    """In-process fence used by the adapter; durable stores still provide CAS."""

    def __init__(self):
        self._tokens = {}
        self._lock = threading.RLock()

    def issue(self, scope: str) -> int:
        with self._lock:
            self._tokens[scope] = self._tokens.get(scope, 0) + 1
            return self._tokens[scope]

    def accept(self, scope: str, token: int) -> None:
        with self._lock:
            current = self._tokens.get(scope, 0)
            if int(token) < current:
                raise RuntimeError("stale fence token")
            self._tokens[scope] = int(token)

    def mutate(self, scope: str, token: int, operation):
        with self._lock:
            if int(token) != self._tokens.get(scope):
                raise RuntimeError("stale fence token")
            return operation()


def _is_denied_payload(payload: dict) -> bool:
    return bool(payload.get("graph_control_point") or payload.get("graph_tombstoned"))


class ActiveSelectorFilter:
    def __init__(self, entries):
        self.entries = list(entries)

    def matches(self, payload: dict) -> bool:
        if _is_denied_payload(payload):
            return False
        return any(
            payload.get("document_id") == entry.get("document_id")
            and payload.get("document_generation") == entry.get("document_generation")
            and payload.get("document_attempt_id") == entry.get("document_attempt_id")
            for entry in self.entries
        )


class VectorFallbackFilter:
    def __init__(self, entries):
        self.entries = list(entries)

    def matches(self, payload: dict) -> bool:
        if _is_denied_payload(payload) or payload.get("graph_point") or not payload.get("vector_point", False):
            return False
        return any(
            payload.get("document_id") == entry.get("document_id")
            and payload.get("document_generation") == entry.get("document_generation")
            for entry in self.entries
        )


def graph_from_artifact(data: dict, chunks: list[dict] | None = None) -> nx.Graph:
    graph = nx.Graph()
    graph.graph.update(data.get("graph_metadata") or {})
    for item in data.get("nodes", []):
        graph.add_node(item["id"], **item.get("attrs", {}))
    for item in data.get("edges", []):
        graph.add_edge(item["source"], item["target"], **item.get("attrs", {}))
    if chunks:
        # Persistent graphs retain full-document topology, but query views only
        # expose retrieved chunk nodes and their connected evidence.
        valid_uids = {chunk.get("chunk_uid") for chunk in chunks}
        for node in list(graph.nodes):
            if graph.nodes[node].get("type") == "chunk" and graph.nodes[node].get("chunk_uid") not in valid_uids:
                graph.remove_node(node)
    return graph


class PersistentGraphReader:
    def __init__(self, manifests: ManifestStore, artifacts: GraphArtifactStore):
        self.manifests = manifests
        self.artifacts = artifacts

    def load(self, document_id: str, chunks: list[dict] | None = None) -> nx.Graph | None:
        entry = self.manifests.get(document_id)
        if not entry or entry.get("status") != "available" or not entry.get("active_artifact_key"):
            return None
        data = self.artifacts.read(
            entry["active_artifact_key"],
            entry.get("artifact_digest"),
            entry.get("backend"),
            entry.get("document_generation"),
            entry.get("source_fingerprint"),
        )
        artifact = deserialize_graph(data)
        if artifact.get("source_fingerprint") != entry.get("source_fingerprint"):
            raise ValueError("graph source fingerprint mismatch")
        graph = graph_from_artifact(artifact, chunks)
        if chunks:
            by_uid = {chunk.get("chunk_uid"): index for index, chunk in enumerate(chunks)}
            mapping = {
                node: f"chunk_{by_uid[attrs.get('chunk_uid')]}"
                for node, attrs in graph.nodes(data=True)
                if attrs.get("type") == "chunk" and attrs.get("chunk_uid") in by_uid
            }
            graph = nx.relabel_nodes(graph, mapping, copy=True)
        return graph


def default_graph_services(collection: str, object_store=None):
    if object_store is None:
        from storage.factory import get_storage_handler

        handler = get_storage_handler()
        object_store = S3ObjectStore(handler)
        backend = {
            "kind": handler.__class__.__name__.replace("Handler", "").lower(),
            "namespace": f"{handler.bucket_name}",
        }
    else:
        backend = {"kind": "injected", "namespace": collection}
    return ManifestStore(object_store, collection, backend=backend), GraphArtifactStore(object_store, collection)


def build_document_graph(chunks, embeddings, document_id, *, entity_extractor=None, graph_builder=None, detector=None):
    """Build the reusable baseline graph from all document chunks."""
    if entity_extractor is None:
        from graph.entity_extractor import EntityExtractor

        entity_extractor = EntityExtractor()
    if graph_builder is None:
        from graph.graph_builder import GraphBuilder

        graph_builder = GraphBuilder()
    if detector is None:
        from graph.community_detector import CommunityDetector

        detector = CommunityDetector()
    entity_map, entities = entity_extractor.extract_entities(chunks)
    relations = []
    for chunk in chunks:
        chunk_uid = chunk.get("chunk_uid", chunk.get("chunk_id"))
        local_entities = entity_map.get(chunk_uid, [])
        extracted = entity_extractor.extract_relations_llm(chunk.get("text", ""), local_entities)
        for relation in extracted:
            relation = dict(relation)
            relation.setdefault("support_chunk_uids", [chunk_uid])
            relation.setdefault("evidence_type", "explicit" if relation.get("source") not in {"rule-based", "fallback"} else "same_chunk")
            relations.append(relation)
    graph = graph_builder.build_graph(chunks, embeddings, entities, relations)
    graph, communities, community_map, modularity = detector.detect(graph)
    diagnostics = {
        "entity_count": len(entities),
        "local_relation_count": len(relations),
        "community_count": len(communities),
        "modularity": modularity,
        "entity_extraction": {"status": "available"},
        "topology": graph.graph.get("topology", {}),
        "community_selection": graph.graph.get("community_selection", {}),
    }
    return graph, {
        "communities": communities,
        "community_map": community_map,
        "modularity": modularity,
        "raw_evidence": graph.graph.get("raw_evidence", []),
        "diagnostics": diagnostics,
    }


class PersistentGraphPipeline:
    def __init__(self, collection: str, object_store=None, manifests=None, artifacts=None):
        if manifests is None or artifacts is None:
            manifests, artifacts = default_graph_services(collection, object_store)
        self.manifests = manifests
        self.artifacts = artifacts

    def reserve(self, chunks, document_id, *, mode="append", operation_id=None):
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        generation = int(prior.get("document_generation", 0)) + 1 if prior else 1
        operation_id = operation_id or f"ingest:{self.manifests.collection}:{document_id}:{generation}:{fingerprint}"
        return self.manifests.reserve(document_id, operation_id, fingerprint, mode=mode)

    def build_and_publish(self, chunks, embeddings, document_id, *, mode="append", operation_id=None, claim=None, **kwargs):
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        generation = claim.get("document_generation") if claim else (int(prior.get("document_generation", 0)) + 1 if prior else 1)
        operation_id = operation_id or f"ingest:{self.manifests.collection}:{document_id}:{generation}:{fingerprint}"
        claim = claim or self.manifests.reserve(document_id, operation_id, fingerprint, mode=mode)
        try:
            graph, details = build_document_graph(chunks, embeddings, document_id, **kwargs)
            canonical = serialize_graph(graph, chunks, document_id, claim["document_generation"], details["raw_evidence"], details["diagnostics"])
            artifact_key, digest = self.artifacts.write(claim, canonical)
            # Read-back validates gzip, immutable bytes, metadata, and digest
            # before the manifest's active pointer is changed.
            self.artifacts.read(artifact_key, digest)
            self.manifests.bind_artifact(claim, artifact_key, digest)
            entry = self.manifests.publish(claim, artifact_key, digest)
            return {"status": entry["status"], "entry": entry, "artifact_key": artifact_key, "artifact_digest": digest, "details": details}
        except Exception as exc:
            try:
                entry = self.manifests.fail(claim, f"{type(exc).__name__}: {exc}")
            except Exception as fail_exc:
                raise RuntimeError("graph failure status CAS failed; claim remains fail-closed") from fail_exc
            return {"status": entry.get("status", "unavailable"), "entry": entry, "failure_reason": str(exc)}

    def backfill(self, chunks, embeddings, document_id, **kwargs):
        """Backfill uses payloads and stored vectors; it never re-embeds text."""
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        if (
            prior
            and prior.get("status") == "available"
            and prior.get("source_fingerprint") == fingerprint
            and prior.get("active_artifact_key")
        ):
            try:
                self.artifacts.read(
                    prior["active_artifact_key"],
                    prior.get("artifact_digest"),
                    prior.get("backend"),
                    prior.get("document_generation"),
                    prior.get("source_fingerprint"),
                )
                return {"status": "available", "entry": prior, "resumed": False}
            except (FileNotFoundError, ValueError):
                pass
        operation_id = f"backfill:{self.manifests.collection}:{document_id}:{fingerprint}"
        claim = None
        if (
            prior
            and prior.get("status") == "pending"
            and prior.get("pending_operation_id") == operation_id
            and prior.get("pending_source_fingerprint") == fingerprint
        ):
            claim = prior
        return self.build_and_publish(
            chunks,
            embeddings or [],
            document_id,
            mode="replace-document" if prior else "append",
            operation_id=operation_id,
            claim=claim,
            **kwargs,
        )


def backfill_qdrant_collection(qdrant, collection: str, *, object_store=None, document_id: str | None = None, **kwargs) -> list[dict]:
    """Build graph artifacts from existing payloads; no embedding call is made."""
    chunks = qdrant.scroll_document_chunks(document_id=document_id, include_vectors=True)
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk.get("document_id"), []).append(chunk)
    pipeline = PersistentGraphPipeline(collection, object_store=object_store)
    results = []
    for current_document_id, document_chunks in sorted(grouped.items()):
        if not current_document_id:
            continue
        vectors = [chunk.pop("_embedding", None) for chunk in document_chunks]
        if not all(vector is not None for vector in vectors):
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "stored vectors are incomplete; rebuild required",
            })
            continue
        results.append(pipeline.backfill(document_chunks, vectors, current_document_id, **kwargs))
    return results
