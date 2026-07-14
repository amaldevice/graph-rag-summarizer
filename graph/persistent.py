"""Small, deterministic document-graph artifact and manifest contract.

The object store is deliberately injected.  Production uses the configured S3
compatible backend; tests use :class:`InMemoryObjectStore` and never need a
network service.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import networkx as nx

from graph.relation_evidence import (
    canonicalize_entities,
    classify_weak_relation_evidence,
    classify_entity_support,
    is_active_relation,
    normalize_relation_evidence,
)
from graph.relation_recovery import (
    cleanup_unsupported_entity_nodes,
    generate_relation_candidates,
    verify_relation_candidates,
)


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
            return text[:-2] if text.endswith(".0") else text
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
        return value
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_MUTATION_LEASE_TTL_SECONDS = 900


def _key_component(value: str) -> str:
    """Keep caller-controlled identifiers inside their object-store prefix."""
    return quote(str(value), safe="-_.~")


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
    active_evidence: list[dict] | None = None,
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
    stable_raw_evidence = sorted(
        (_json_safe(item) for item in (raw_evidence or [])),
        key=canonical_json_bytes,
    )
    stable_active_evidence = sorted(
        (_json_safe(item) for item in (active_evidence or [])),
        key=canonical_json_bytes,
    )
    payload = {
        "schema_version": 1,
        "document_id": document_id,
        "document_generation": int(generation),
        "source_fingerprint": source_fingerprint(chunks, document_id),
        "chunks": chunk_refs,
        "nodes": nodes,
        "edges": edges,
        "raw_evidence": stable_raw_evidence,
        "active_evidence": stable_active_evidence,
        "diagnostics": _json_safe(diagnostics or {}),
        "graph_metadata": _json_safe(dict(graph.graph)),
    }
    return canonical_json_bytes(payload)


def deserialize_graph(data: bytes | str) -> dict:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return json.loads(data.decode("utf-8"))


class GraphArtifactCorruptionError(ValueError):
    """The immutable graph artifact cannot be trusted as a query fallback."""


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
        endpoint = getattr(getattr(self.client, "meta", None), "endpoint_url", "")
        self.backend_authority = {
            "kind": handler.__class__.__name__.replace("Handler", "").lower(),
            "namespace": f"{endpoint}|{self.bucket}",
        }
        explicit_capability = getattr(handler, "supports_conditional_cas", None)
        if explicit_capability is None:
            service_model = getattr(getattr(self.client, "meta", None), "service_model", None)
            try:
                members = service_model.operation_model("PutObject").input_shape.members
            except AttributeError:
                members = set()
            explicit_capability = {"IfMatch", "IfNoneMatch"}.issubset(members)
        self.supports_conditional_cas = bool(explicit_capability)
        self.fencing_enforced = self.supports_conditional_cas

    @staticmethod
    def is_conditional_conflict(exc: Exception) -> bool:
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        code = str(error.get("Code", ""))
        status = str((response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}).get("HTTPStatusCode", ""))
        return code in {"PreconditionFailed", "ConditionalRequestConflict", "412"} or status == "412"

    def put(self, key: str, data: bytes, *, if_none_match: bool = False, if_match: str | None = None, metadata=None) -> str:
        # ponytail: ETag If-Match is the atomic CAS; the metadata check rejects stale tokens early.
        metadata = dict(metadata or {})
        requested_fence = int(metadata.get("fence_token", 0))
        object_exists = False
        try:
            current_metadata, current_etag = self.head(key)
            object_exists = True
        except Exception as exc:
            if "404" not in str(exc) and "NoSuchKey" not in str(exc) and "Not Found" not in str(exc):
                raise
            current_metadata, current_etag = {}, None
        current_fence = int(current_metadata.get("fence_token", 0))
        if requested_fence < current_fence:
            raise RuntimeError("object fence token is stale")
        if object_exists and not current_etag:
            raise RuntimeError("existing object has no ETag; conditional write cannot be enforced")
        if object_exists and if_match is None and not if_none_match:
            raise RuntimeError("conditional write is required for an existing object")
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
        return str(PurePosixPath("graphs", _key_component(self.collection), _key_component(document_id), f"v{int(version)}", "graph.json.gz"))

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
        except Exception as exc:
            is_conflict = isinstance(exc, FileExistsError) or bool(
                getattr(self.object_store, "is_conditional_conflict", lambda error: False)(exc)
            )
            if not is_conflict:
                raise
            existing, existing_metadata, _ = self.object_store.get(key)
            if (
                gzip.decompress(existing) != canonical_bytes
                or existing_metadata.get("artifact_digest") != digest
                or existing_metadata.get("document_generation") != str(claim["document_generation"])
                or existing_metadata.get("source_fingerprint") != str(claim.get("source_fingerprint", ""))
                or existing_metadata.get("operation_id") != str(claim.get("operation_id", ""))
                or existing_metadata.get("pending_attempt_id") != str(claim.get("pending_attempt_id", ""))
                or existing_metadata.get("build_attempt_id") != str(claim.get("build_attempt_id", ""))
                or existing_metadata.get("backend_kind") != str(backend.get("kind", ""))
                or existing_metadata.get("backend_namespace") != str(backend.get("namespace", ""))
            ):
                raise ValueError("immutable graph artifact key contains different bytes")
        return key, digest

    def read(self, key: str, expected_digest: str | None = None, expected_backend: dict | None = None, expected_generation: int | None = None, expected_source_fingerprint: str | None = None) -> bytes:
        compressed, metadata, _ = self.object_store.get(key)
        try:
            data = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise GraphArtifactCorruptionError("graph artifact gzip payload is corrupt") from exc
        digest = _digest(data)
        if expected_digest and digest != expected_digest:
            raise GraphArtifactCorruptionError("graph artifact digest mismatch")
        if not metadata.get("artifact_digest"):
            raise GraphArtifactCorruptionError("graph artifact metadata is missing digest")
        if metadata["artifact_digest"] != digest:
            raise GraphArtifactCorruptionError("graph artifact metadata mismatch")
        if expected_generation is not None and metadata.get("document_generation") != str(expected_generation):
            raise GraphArtifactCorruptionError("graph artifact generation mismatch")
        if expected_source_fingerprint is not None and metadata.get("source_fingerprint") != str(expected_source_fingerprint):
            raise GraphArtifactCorruptionError("graph artifact source fingerprint mismatch")
        if expected_backend and (
            not metadata.get("backend_kind")
            or metadata.get("backend_kind") != str(expected_backend.get("kind", ""))
            or metadata.get("backend_namespace") != str(expected_backend.get("namespace", ""))
        ):
            raise ValueError("graph artifact backend mismatch")
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GraphArtifactCorruptionError("graph artifact is not valid JSON") from exc
        try:
            canonical = canonical_json_bytes(decoded)
        except (TypeError, ValueError) as exc:
            raise GraphArtifactCorruptionError("graph artifact is not canonical JSON") from exc
        if canonical != data:
            raise GraphArtifactCorruptionError("graph artifact is not canonical JSON")
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
        if not getattr(object_store, "supports_conditional_cas", False) or not getattr(object_store, "fencing_enforced", False):
            raise RuntimeError(
                "persistent graph manifest backend must provide conditional CAS and durable fencing"
            )
        # ponytail: this lock only reduces same-process duplicate reads; object-store CAS is authority.
        self._lock = threading.RLock()
        self.manifest_key = str(PurePosixPath("graphs", _key_component(collection), "manifest.json"))

    def _default(self) -> dict:
        return {
            "schema_version": 1,
            "collection": self.collection,
            "manifest_revision": 0,
            "manifest_fence_token": 0,
            "tombstone_epoch": 0,
            "collection_fence_token": 0,
            "collection_operation_id": None,
            "collection_attempt_id": None,
            "collection_retained_documents": None,
            "active_mutation_id": None,
            "active_mutation_scope": None,
            "active_mutation_operation_id": None,
            "active_mutation_document_id": None,
            "active_mutation_attempt_id": None,
            "active_mutation_started_at": None,
            "active_mutation_pid": None,
            "active_mutation_host": None,
            "manifest_backend": self.backend,
            "tombstone_set_digest": _digest(canonical_json_bytes([])),
            "pending_tombstone_set_digest": None,
            "pending_tombstone_cleanup_ids": [],
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
                int(manifest.get("manifest_fence_token", 0)),
            )

    def _assert_snapshot_current(self, expected: ManifestSnapshot) -> None:
        current = self.read_snapshot()
        if (
            current.data != expected.data
            or current.etag != expected.etag
            or current.manifest_revision != expected.manifest_revision
            or current.digest != expected.digest
            or current.fence_token != expected.fence_token
        ):
            raise RuntimeError("manifest snapshot changed before CAS")

    def revalidate(self, snapshot: ManifestSnapshot) -> bool:
        current = self.read_snapshot()
        return (
            current.digest == snapshot.digest
            and current.etag == snapshot.etag
            and current.fence_token == snapshot.fence_token
        )

    def _write(self, manifest: dict, expected: ManifestSnapshot) -> dict:
        if not getattr(self.object_store, "supports_conditional_cas", False):
            raise RuntimeError("manifest backend cannot enforce conditional CAS")
        if not getattr(self.object_store, "fencing_enforced", False):
            raise RuntimeError("manifest backend cannot enforce durable fencing")
        self._assert_snapshot_current(expected)
        manifest = dict(manifest)
        if int(manifest.get("manifest_revision", 0)) != expected.manifest_revision:
            raise RuntimeError("manifest candidate revision does not match its snapshot")
        manifest["manifest_revision"] = expected.manifest_revision + 1
        manifest["manifest_fence_token"] = int(expected.fence_token or 0) + 1
        data = canonical_json_bytes(manifest)
        kwargs = {"metadata": {
            "manifest_revision": str(manifest["manifest_revision"]),
            "fence_token": str(manifest["manifest_fence_token"]),
        }}
        if expected.etag is None:
            kwargs["if_none_match"] = True
        else:
            kwargs["if_match"] = expected.etag
        self.object_store.put(self.manifest_key, data, **kwargs)
        return manifest

    def get(self, document_id: str) -> dict | None:
        return self._read()[0].get("documents", {}).get(document_id)

    def entries(self) -> dict[str, dict]:
        return dict(self._read()[0].get("documents", {}))

    def assert_claim_current(self, claim: dict) -> None:
        with self._lock:
            manifest, _ = self._read()
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
                raise RuntimeError("stale graph claim cannot mutate Qdrant")

    @staticmethod
    def _mutation_lease_matches(
        manifest: dict,
        *,
        scope: str,
        operation_id: str,
        document_id: str | None,
        attempt_id: str | None,
    ) -> bool:
        return (
            manifest.get("active_mutation_scope") == scope
            and manifest.get("active_mutation_operation_id") == operation_id
            and manifest.get("active_mutation_document_id") == document_id
            and manifest.get("active_mutation_attempt_id") == attempt_id
        )

    @staticmethod
    def _mutation_lease_expired(manifest: dict) -> bool:
        started_at = manifest.get("active_mutation_started_at")
        if not isinstance(started_at, str):
            return False
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started).total_seconds() > _MUTATION_LEASE_TTL_SECONDS

    @staticmethod
    def _mutation_owner_alive(manifest: dict) -> bool:
        pid = manifest.get("active_mutation_pid")
        host = manifest.get("active_mutation_host")
        if not isinstance(pid, int) or not isinstance(host, str):
            return True
        if host != socket.gethostname():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True

    def _acquire_mutation_lease(
        self,
        snapshot: ManifestSnapshot,
        *,
        scope: str,
        operation_id: str,
        document_id: str | None,
        attempt_id: str | None,
    ) -> str:
        manifest = snapshot.manifest
        if manifest.get("active_mutation_id") is not None and not (
            self._mutation_lease_matches(
                manifest,
                scope=scope,
                operation_id=operation_id,
                document_id=document_id,
                attempt_id=attempt_id,
            )
            and self._mutation_lease_expired(manifest)
            and not self._mutation_owner_alive(manifest)
        ):
            raise RuntimeError("a Qdrant mutation is already fenced")
        owner = str(uuid.uuid4())
        manifest.update({
            "active_mutation_id": owner,
            "active_mutation_scope": scope,
            "active_mutation_operation_id": operation_id,
            "active_mutation_document_id": document_id,
            "active_mutation_attempt_id": attempt_id,
            "active_mutation_started_at": _now(),
            "active_mutation_pid": os.getpid(),
            "active_mutation_host": socket.gethostname(),
        })
        self._write(manifest, snapshot)
        return owner

    def _release_mutation_lease(self, owner: str) -> None:
        snapshot = self.read_snapshot()
        manifest = snapshot.manifest
        if manifest.get("active_mutation_id") != owner:
            raise RuntimeError("Qdrant mutation lease was lost")
        manifest.update({
            "active_mutation_id": None,
            "active_mutation_scope": None,
            "active_mutation_operation_id": None,
            "active_mutation_document_id": None,
            "active_mutation_attempt_id": None,
            "active_mutation_started_at": None,
            "active_mutation_pid": None,
            "active_mutation_host": None,
        })
        self._write(manifest, snapshot)

    def mutate_claim(self, claim: dict, operation):
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            current = manifest.get("documents", {}).get(claim["document_id"])
            if (
                not self._claim_matches(current, claim)
                or not self._claim_matches_collection(manifest, claim)
            ):
                raise RuntimeError("stale graph claim cannot mutate Qdrant")
            owner = self._acquire_mutation_lease(
                snapshot,
                scope="document",
                operation_id=claim["operation_id"],
                document_id=claim["document_id"],
                attempt_id=claim.get("pending_attempt_id"),
            )
            operation_error = None
            result = None
            try:
                result = operation()
                manifest, _ = self._read()
                current = manifest.get("documents", {}).get(claim["document_id"])
                if (
                    manifest.get("active_mutation_id") != owner
                    or not self._claim_matches(current, claim)
                    or not self._claim_matches_collection(manifest, claim)
                ):
                    raise RuntimeError("graph claim changed during Qdrant mutation")
            except Exception as exc:
                operation_error = exc
            try:
                self._release_mutation_lease(owner)
            except Exception as release_error:
                if operation_error is None:
                    raise RuntimeError("graph mutation lease could not be released") from release_error
                raise RuntimeError("graph mutation failed and lease could not be released") from operation_error
            if operation_error is not None:
                raise operation_error
            return result

    def mutate_collection(self, operation_id: str, fence_token: int, operation, attempt_id: str | None = None):
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if not self._collection_fence_matches(manifest, operation_id, fence_token, attempt_id):
                raise RuntimeError("stale collection fence cannot mutate Qdrant")
            owner = self._acquire_mutation_lease(
                snapshot,
                scope="collection",
                operation_id=operation_id,
                document_id=None,
                attempt_id=attempt_id,
            )
            operation_error = None
            result = None
            try:
                result = operation()
                manifest, _ = self._read()
                if (
                    manifest.get("active_mutation_id") != owner
                    or not self._collection_fence_matches(manifest, operation_id, fence_token, attempt_id)
                ):
                    raise RuntimeError("collection fence changed during Qdrant mutation")
            except Exception as exc:
                operation_error = exc
            try:
                self._release_mutation_lease(owner)
            except Exception as release_error:
                if operation_error is None:
                    raise RuntimeError("collection mutation lease could not be released") from release_error
                raise RuntimeError("collection mutation failed and lease could not be released") from operation_error
            if operation_error is not None:
                raise operation_error
            return result

    @staticmethod
    def _collection_fence_matches(manifest: dict, operation_id: str, fence_token: int, attempt_id: str | None) -> bool:
        return bool(
            manifest.get("collection_operation_id") == operation_id
            and (attempt_id is None or manifest.get("collection_attempt_id") == attempt_id)
            and manifest.get("pending_tombstone_set_digest") in {"pending", None}
            and int(manifest.get("collection_fence_token", 0)) == int(fence_token)
        )

    @staticmethod
    def _collection_fence_allows_reservation(
        manifest: dict,
        document_id: str,
        operation_id: str,
        source_fingerprint_value: str,
        mode: str,
    ) -> bool:
        """Allow only the replacement target bound to the current collection fence."""
        active_operation = manifest.get("collection_operation_id")
        if active_operation is None:
            return True
        attempt_id = manifest.get("collection_attempt_id")
        retained_documents = manifest.get("collection_retained_documents")
        return bool(
            mode == "replace-collection"
            and operation_id == active_operation
            and isinstance(attempt_id, str)
            and attempt_id
            and isinstance(retained_documents, dict)
            and retained_documents.get(document_id) == source_fingerprint_value
            and manifest.get("pending_tombstone_set_digest") in {"pending", None}
        )

    def reserve(
        self,
        document_id: str,
        operation_id: str,
        source_fingerprint_value: str,
        *,
        mode: str = "append",
        document_generation: int | None = None,
    ) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            documents = dict(manifest.get("documents", {}))
            prior = documents.get(document_id)
            if not self._collection_fence_allows_reservation(
                manifest,
                document_id,
                operation_id,
                source_fingerprint_value,
                mode,
            ):
                raise RuntimeError("collection replacement fence rejects unrelated document reservation")
            if document_generation is not None and (
                isinstance(document_generation, bool)
                or not isinstance(document_generation, int)
                or document_generation <= 0
            ):
                raise ValueError("document generation must be a positive integer")
            if prior and document_generation is not None:
                prior_generation = prior.get("document_generation")
                if (
                    isinstance(prior_generation, bool)
                    or not isinstance(prior_generation, int)
                    or prior_generation != document_generation
                ):
                    raise ValueError("manifest document generation conflicts with the backfill generation")
            if (
                prior
                and prior.get("pending_operation_id") == operation_id
                and prior.get("pending_source_fingerprint") == source_fingerprint_value
                and self._claim_matches_collection(manifest, prior)
            ):
                return prior
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            if mode == "append" and prior is not None:
                raise ValueError(f"document '{document_id}' is already tracked; use replace-document")
            if prior and prior.get("pending_operation_id") and (
                prior["pending_operation_id"] != operation_id
                or not self._claim_matches_collection(manifest, prior)
            ):
                superseded_operation = prior["pending_operation_id"]
                prior = dict(prior)
                prior["version_ledger"] = [dict(item) for item in prior.get("version_ledger", [])]
                for item in prior["version_ledger"]:
                    if item.get("operation_id") == superseded_operation and item.get("state") == "reserved":
                        item.update({"state": "burned", "updated_at": _now()})
                prior.update({
                    "status": "partial" if prior.get("active_artifact_key") else "unavailable",
                    "pending_operation_id": None,
                    "pending_generation": None,
                    "pending_source_fingerprint": None,
                    "pending_version": None,
                    "pending_attempt_id": None,
                    "pending_backend": None,
                    "pending_artifact_key": None,
                    "pending_artifact_digest": None,
                    "build_attempt_id": None,
                    "failure_reason": f"superseded by operation {operation_id}",
                    "updated_at": _now(),
                })
                documents[document_id] = prior
            generation = document_generation if document_generation is not None else (
                int(prior.get("document_generation", 0)) + 1 if prior else 1
            )
            ledger = list(prior.get("version_ledger", [])) if prior else []
            ledger_next_version = max(
                (int(item.get("version", 0)) for item in ledger),
                default=0,
            ) + 1
            next_version = max(int(prior.get("next_version", 1)), ledger_next_version) if prior else 1
            previous_pointer = prior.get("previous_pointer") if prior else None
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
                "vector_ready": False,
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
                "collection_attempt_id": manifest.get("collection_attempt_id"),
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
            return self._write(manifest, snapshot) and claim

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
            "collection_attempt_id",
            "document_fence_token",
            "pending_backend",
        )
        return bool(
            current
            and all(current.get(field) == claim.get(field) for field in fields)
        )

    @staticmethod
    def _claim_matches_collection(manifest: dict, claim: dict) -> bool:
        return (
            int(manifest.get("collection_fence_token", 0)) == int(claim.get("collection_fence_token", 0))
            and manifest.get("collection_attempt_id") == claim.get("collection_attempt_id")
        )

    def publish(self, claim: dict, artifact_key: str, artifact_digest: str) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
                raise RuntimeError("stale graph claim cannot publish")
            if (
                current.get("pending_artifact_key") != artifact_key
                or current.get("pending_artifact_digest") != artifact_digest
            ):
                raise RuntimeError("published artifact does not match the pending claim")
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
                "vector_ready": True,
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
            if manifest.get("pending_tombstone_cleanup_ids"):
                manifest["tombstone_set_digest"] = self.tombstone_proof_digest(manifest)
                manifest["pending_tombstone_set_digest"] = None
                manifest["pending_tombstone_cleanup_ids"] = []
            self._write(manifest, snapshot)
            return current

    def mark_vectors_ready(self, claim: dict) -> dict:
        """Record that the Qdrant vector/control proof completed before graph publication."""
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
                raise RuntimeError("stale graph claim cannot mark vectors ready")
            current = dict(current)
            current["vector_ready"] = True
            current["updated_at"] = _now()
            manifest["documents"][claim["document_id"]] = current
            self._write(manifest, snapshot)
            return current

    def bind_artifact(self, claim: dict, artifact_key: str, artifact_digest: str) -> dict:
        """Record the pending immutable blob before the activation CAS."""
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
                raise RuntimeError("stale graph claim cannot bind artifact")
            current = dict(current)
            current["pending_artifact_key"] = artifact_key
            current["pending_artifact_digest"] = artifact_digest
            for item in current.get("version_ledger", []):
                if item.get("version") == claim.get("pending_version"):
                    item.update({
                        "artifact_key": artifact_key,
                        "artifact_digest": artifact_digest,
                        "updated_at": _now(),
                    })
            manifest["documents"][claim["document_id"]] = current
            self._write(manifest, snapshot)
            return current

    @staticmethod
    def _retained_document_fingerprints(retained_documents: dict[str, str]) -> dict[str, str]:
        """Validate the immutable replacement target set before acquiring its fence."""
        if not isinstance(retained_documents, dict):
            raise TypeError("replace-collection retained documents must map IDs to source fingerprints")
        normalized = {}
        for document_id, fingerprint in retained_documents.items():
            if not isinstance(document_id, str) or not document_id:
                raise ValueError("replace-collection retained document IDs must be non-empty strings")
            if not isinstance(fingerprint, str) or not fingerprint:
                raise ValueError("replace-collection source fingerprints must be non-empty strings")
            normalized[document_id] = fingerprint
        return dict(sorted(normalized.items()))

    def tombstone_documents(self, retained_documents: dict[str, str], operation_id: str) -> dict:
        """Make omitted documents non-discoverable and bind the replacement target set."""
        retained_document_fingerprints = self._retained_document_fingerprints(retained_documents)
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            active_operation = manifest.get("collection_operation_id")
            if active_operation:
                if active_operation != operation_id:
                    raise RuntimeError("collection has an active tombstone operation")
                if manifest.get("collection_retained_documents") != retained_document_fingerprints:
                    raise RuntimeError("collection replacement target does not match the active fence")
                return manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            documents = dict(manifest.get("documents", {}))
            cleanup_ids = []
            manifest["tombstone_epoch"] = int(manifest.get("tombstone_epoch", 0)) + 1
            for document_id, entry in documents.items():
                if document_id in retained_document_fingerprints:
                    if entry.get("status") == "tombstoned":
                        entry = dict(entry)
                        cleanup_ids.append(str(uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"graph-control:tombstone:{self.collection}:{document_id}",
                        )))
                        entry.update({
                            "status": "pending",
                            "tombstone_operation_id": None,
                            "tombstone_attempt_id": None,
                            "tombstone_fence_token": None,
                            "failure_reason": None,
                            "updated_at": _now(),
                        })
                        documents[document_id] = entry
                    continue
                entry = dict(entry)
                prior_active_version = entry.get("active_version")
                prior_pending_version = entry.get("pending_version")
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
                    "tombstone_attempt_id": f"{operation_id}:{uuid.uuid4()}",
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
                    "pending_generation": None,
                    "pending_source_fingerprint": None,
                    "build_attempt_id": None,
                    "updated_at": _now(),
                    "failure_reason": "omitted by replace-collection",
                })
                self._burn_tombstone_versions_for_entry(
                    entry,
                    active_version=prior_active_version,
                    pending_version=prior_pending_version,
                )
                documents[document_id] = entry
            manifest["documents"] = documents
            manifest["collection_fence_token"] = int(manifest.get("collection_fence_token", 0)) + 1
            manifest["collection_operation_id"] = operation_id
            manifest["collection_attempt_id"] = f"{operation_id}:{uuid.uuid4()}"
            manifest["collection_retained_documents"] = retained_document_fingerprints
            manifest["pending_tombstone_cleanup_ids"] = sorted(cleanup_ids)
            manifest["pending_tombstone_set_digest"] = "pending"
            self._write(manifest, snapshot)
            return manifest

    def _burn_tombstone_versions_for_entry(
        self,
        entry: dict,
        *,
        active_version: int | None,
        pending_version: int | None,
    ) -> None:
        for item in entry.get("version_ledger", []):
            if item.get("version") == active_version:
                item.update({"state": "tombstoned", "updated_at": _now()})
            elif item.get("version") == pending_version and item.get("state") == "reserved":
                item.update({"state": "burned", "updated_at": _now()})

    def tombstone_controls(self, manifest: dict | None = None) -> list[dict]:
        manifest = manifest or self.read_snapshot().manifest
        controls = []
        for document_id, entry in manifest.get("documents", {}).items():
            if entry.get("status") != "tombstoned":
                continue
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"graph-control:tombstone:{self.collection}:{document_id}",
            ))
            controls.append({
                "point_id": point_id,
                "payload": {
                    "graph_control_point": "tombstone",
                    "graph_point": True,
                    "graph_tombstoned": True,
                    "tombstone_complete": True,
                    "document_id": document_id,
                    "document_generation": entry.get("document_generation"),
                    "tombstone_epoch": int(manifest.get("tombstone_epoch", 0)),
                    "tombstone_operation_id": manifest.get("collection_operation_id") or entry.get("tombstone_operation_id"),
                    "tombstone_attempt_id": entry.get("tombstone_attempt_id"),
                    "tombstone_fence_token": int(entry.get("tombstone_fence_token", 0)),
                    "collection_fence_token": int(manifest.get("collection_fence_token", 0)),
                    "collection_attempt_id": manifest.get("collection_attempt_id"),
                },
            })
        return sorted(controls, key=lambda item: item["point_id"])

    def tombstone_proof_digest(self, manifest: dict) -> str:
        return _digest(canonical_json_bytes(self.tombstone_controls(manifest)))

    def commit_tombstone_proof(self, proofs: list[dict]) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            expected = self.tombstone_controls(manifest)
            if manifest.get("pending_tombstone_set_digest") != "pending":
                raise RuntimeError("no pending tombstone proof")
            ordered = sorted(proofs, key=lambda item: str(item["point_id"]))
            if ordered != expected:
                raise RuntimeError("tombstone proof does not cover the committed deny set")
            if manifest.get("pending_tombstone_cleanup_ids"):
                manifest["pending_tombstone_set_digest"] = "pending"
            else:
                manifest["tombstone_set_digest"] = self.tombstone_proof_digest(manifest)
                manifest["pending_tombstone_set_digest"] = None
            self._write(manifest, snapshot)
            return manifest

    def finalize_tombstone_cleanup(self, operation_id: str, fence_token: int) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            if (
                manifest.get("collection_operation_id") != operation_id
                or int(manifest.get("collection_fence_token", 0)) != int(fence_token)
                or (
                    manifest.get("pending_tombstone_cleanup_ids")
                    and manifest.get("pending_tombstone_set_digest") != "pending"
                )
                or (
                    not manifest.get("pending_tombstone_cleanup_ids")
                    and manifest.get("pending_tombstone_set_digest") is not None
                )
            ):
                raise RuntimeError("stale tombstone cleanup cannot finalize")
            manifest["tombstone_set_digest"] = self.tombstone_proof_digest(manifest)
            manifest["pending_tombstone_set_digest"] = None
            manifest["pending_tombstone_cleanup_ids"] = []
            self._write(manifest, snapshot)
            return manifest

    def release_collection_fence(self, operation_id: str, fence_token: int) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            if (
                manifest.get("collection_operation_id") != operation_id
                or int(manifest.get("collection_fence_token", 0)) != int(fence_token)
                or manifest.get("pending_tombstone_set_digest") is not None
            ):
                raise RuntimeError("stale collection fence cannot be released")
            manifest["collection_operation_id"] = None
            manifest["collection_attempt_id"] = None
            manifest["collection_retained_documents"] = None
            self._write(manifest, snapshot)
            return manifest

    def preflight(self, document_id: str) -> dict:
        """Fail closed for tombstones before compatibility fallback."""
        manifest, _ = self._read()
        entry = manifest.get("documents", {}).get(document_id)
        if manifest.get("pending_tombstone_set_digest") is not None or manifest.get("collection_operation_id"):
            return {"allowed": False, "reason": "tombstone_proof_pending", "entry": entry}
        if entry and entry.get("status") == "tombstoned":
            return {"allowed": False, "reason": "tombstoned", "entry": entry}
        return {"allowed": True, "reason": "not_denied", "entry": entry}

    def fail(self, claim: dict, reason: str) -> dict:
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
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
            self._write(manifest, snapshot)
            return current

    def stale(self, claim: dict, reason: str) -> dict:
        """Terminally fence a claim after a Qdrant ownership/proof mismatch."""
        with self._lock:
            snapshot = self.read_snapshot()
            manifest = snapshot.manifest
            if manifest.get("active_mutation_id") is not None:
                raise RuntimeError("a Qdrant mutation is already fenced")
            current = manifest.get("documents", {}).get(claim["document_id"])
            if not self._claim_matches(current, claim) or not self._claim_matches_collection(manifest, claim):
                raise RuntimeError("stale graph claim cannot transition stale")
            current = dict(current)
            current.update({
                "status": "stale",
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
            self._write(manifest, snapshot)
            return current


def _is_denied_payload(payload: dict) -> bool:
    return bool(payload.get("graph_control_point") or payload.get("graph_tombstoned"))


class ActiveSelectorFilter:
    def __init__(self, entries):
        self.entries = list(entries)

    def matches(self, payload: dict) -> bool:
        if _is_denied_payload(payload):
            return False
        if not payload.get("graph_point") or payload.get("graph_control_point"):
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
        retained_chunks = [
            node for node, attrs in graph.nodes(data=True)
            if attrs.get("type") == "chunk"
        ]
        connected_evidence = set()
        for chunk_node in retained_chunks:
            connected_evidence.update(nx.node_connected_component(graph, chunk_node))
        graph.remove_nodes_from(set(graph.nodes) - connected_evidence)
    return graph


class PersistentGraphReader:
    def __init__(self, manifests: ManifestStore, artifacts: GraphArtifactStore):
        self.manifests = manifests
        self.artifacts = artifacts

    def load(self, document_id: str, chunks: list[dict] | None = None) -> nx.Graph | None:
        snapshot = self.manifests.read_snapshot()
        entry = snapshot.manifest.get("documents", {}).get(document_id)
        if not entry or entry.get("status") != "available" or not entry.get("active_artifact_key"):
            return None
        data = self.artifacts.read(
            entry["active_artifact_key"],
            entry.get("artifact_digest"),
            entry.get("backend"),
            entry.get("document_generation"),
            entry.get("source_fingerprint"),
        )
        try:
            artifact = deserialize_graph(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GraphArtifactCorruptionError("graph artifact body is not valid JSON") from exc
        if (
            not isinstance(artifact, dict)
            or
            artifact.get("document_id") != document_id
            or artifact.get("document_generation") != entry.get("document_generation")
            or artifact.get("source_fingerprint") != entry.get("source_fingerprint")
        ):
            raise GraphArtifactCorruptionError("graph artifact body metadata mismatch")
        if not self.manifests.revalidate(snapshot):
            raise RuntimeError("manifest changed while reading graph artifact")
        try:
            graph = graph_from_artifact(artifact, chunks)
            if chunks:
                by_uid = {chunk.get("chunk_uid"): index for index, chunk in enumerate(chunks)}
                mapping = {
                    node: f"chunk_{by_uid[attrs.get('chunk_uid')]}"
                    for node, attrs in graph.nodes(data=True)
                    if attrs.get("type") == "chunk" and attrs.get("chunk_uid") in by_uid
                }
                graph = nx.relabel_nodes(graph, mapping, copy=True)
        except (KeyError, TypeError, ValueError, nx.NetworkXError) as exc:
            raise GraphArtifactCorruptionError("graph artifact graph structure is invalid") from exc
        return graph


def default_graph_services(collection: str, object_store=None):
    if object_store is None:
        from storage.factory import get_storage_handler

        handler = get_storage_handler()
        object_store = S3ObjectStore(handler)
        backend = object_store.backend_authority
    else:
        backend = {"kind": "injected", "namespace": collection}
    return ManifestStore(object_store, collection, backend=backend), GraphArtifactStore(object_store, collection)


def build_document_graph(
    chunks,
    embeddings,
    document_id,
    *,
    entity_extractor=None,
    graph_builder=None,
    detector=None,
    relation_provider=None,
):
    """Build a document graph with bounded recovery before community detection."""
    if entity_extractor is None:
        from graph.entity_extractor import EntityExtractor

        entity_extractor = EntityExtractor(provider_router=relation_provider)
    if graph_builder is None:
        from graph.graph_builder import GraphBuilder

        graph_builder = GraphBuilder()
    if detector is None:
        from graph.community_detector import CommunityDetector

        detector = CommunityDetector()
    entity_map, extracted_entities = entity_extractor.extract_entities(chunks)
    entities, canonicalization = canonicalize_entities(extracted_entities)
    mentions_by_chunk_uid = {}
    for mention in extracted_entities:
        mention_chunk_uid = mention.get("chunk_uid")
        if mention_chunk_uid is None:
            mention_chunk_uid = mention.get("chunk_id")
        mentions_by_chunk_uid.setdefault(mention_chunk_uid, []).append(mention)
    local_relations = []
    for chunk in chunks:
        chunk_uid = chunk.get("chunk_uid", chunk.get("chunk_id"))
        local_entities = entity_map.get(chunk_uid, [])
        extracted = entity_extractor.extract_relations_llm(chunk.get("text", ""), local_entities)
        local_mentions = mentions_by_chunk_uid.get(chunk_uid, [])
        extracted = [
            {
                **relation,
                "evidence_type": classify_weak_relation_evidence(relation, local_mentions),
            }
            if str(relation.get("source", "")).casefold() in {"rule-based", "fallback"}
            else relation
            for relation in extracted
        ]
        local_relations.extend(
            normalize_relation_evidence(extracted, support_chunk_uid=chunk_uid)
        )
    local_relations.sort(key=canonical_json_bytes)

    # The first graph is intentionally only a bounded-neighborhood source.  It
    # is rebuilt after verification so accepted evidence is the only recovery
    # output that can become an active direct relation edge.
    graph = graph_builder.build_graph(chunks, embeddings, entities, local_relations)
    query_protected_chunk_uids = {
        str(chunk.get("chunk_uid", chunk.get("chunk_id")))
        for chunk in chunks
        if chunk.get("query_protected")
        and chunk.get("chunk_uid", chunk.get("chunk_id")) is not None
    }
    pre_recovery_support = classify_entity_support(
        entities,
        local_relations,
        graph=graph,
        query_protected_chunk_uids=query_protected_chunk_uids,
    )
    recovery_chunks = [
        {**chunk, "document_id": str(chunk.get("document_id", document_id))}
        for chunk in chunks
    ]
    recovery_candidates = generate_relation_candidates(
        recovery_chunks,
        entities,
        graph,
        pre_recovery_support,
    )
    recovered_evidence, verification_outcomes = verify_relation_candidates(
        recovery_candidates["generated"],
        recovery_chunks,
        graph,
        local_relations,
        relation_provider,
    )
    relations = normalize_relation_evidence([*local_relations, *recovered_evidence])
    graph = graph_builder.build_graph(chunks, embeddings, entities, relations)
    # Rejected, insufficient, and unavailable candidates remain raw audit
    # records only. They must not alter support classification or shield an
    # otherwise isolated entity from the post-recovery cleanup policy.
    support_relations = [
        *local_relations,
        *(relation for relation in recovered_evidence if is_active_relation(relation)),
    ]
    post_recovery_support = classify_entity_support(
        entities,
        support_relations,
        graph=graph,
        query_protected_chunk_uids=query_protected_chunk_uids,
    )
    cleanup = cleanup_unsupported_entity_nodes(graph, post_recovery_support)
    graph, communities, community_map, modularity = detector.detect(graph)
    active_evidence = [
        relation for relation in relations
        if is_active_relation(relation)
    ]
    status_counts = {
        status: sum(1 for relation in relations if relation.get("status") == status)
        for status in sorted({relation.get("status", "unknown") for relation in relations})
    }
    relation_extraction_mode = getattr(entity_extractor, "relation_extraction_mode", "unavailable")
    if relation_extraction_mode not in {"spacy-only", "llm-enhanced", "unavailable"}:
        relation_extraction_mode = "unavailable"
    diagnostics = {
        "entity_count": len(entities),
        "local_relation_count": len(local_relations),
        "raw_evidence_count": len(relations),
        "active_evidence_count": len(active_evidence),
        "relation_status_counts": status_counts,
        "canonicalization": canonicalization,
        "entity_support": classify_entity_support(
            entities,
            support_relations,
            graph=graph,
            query_protected_chunk_uids=query_protected_chunk_uids,
        ),
        "relation_recovery": {
            "candidate_generation": recovery_candidates,
            "verification": verification_outcomes,
            "cleanup": cleanup,
            "counts": {
                "local": len(local_relations),
                "cross_chunk": len(recovered_evidence),
                "accepted": sum(
                    1 for relation in recovered_evidence
                    if relation.get("status") == "accepted"
                ),
                "rejected": sum(
                    1 for relation in recovered_evidence
                    if relation.get("status") == "rejected"
                ),
                "unverified": sum(
                    1 for relation in recovered_evidence
                    if relation.get("status") in {"insufficient", "unavailable"}
                ),
            },
        },
        "community_count": len(communities),
        "modularity": modularity,
        "entity_extraction": {
            "status": "available" if entities else "unavailable",
            "entity_count": len(entities),
        },
        "relation_extraction": {
            "mode": relation_extraction_mode,
        },
        "topology": graph.graph.get("topology", {}),
        "community_selection": graph.graph.get("community_selection", {}),
    }
    return graph, {
        "communities": communities,
        "community_map": community_map,
        "modularity": modularity,
        "raw_evidence": relations,
        "active_evidence": active_evidence,
        "diagnostics": diagnostics,
    }


class GraphLifecycleError(RuntimeError):
    """A graph claim could not reach a durable terminal state."""


class PersistentGraphPipeline:
    def __init__(self, collection: str, object_store=None, manifests=None, artifacts=None):
        if manifests is None or artifacts is None:
            manifests, artifacts = default_graph_services(collection, object_store)
        self.manifests = manifests
        self.artifacts = artifacts

    def reserve(self, chunks, document_id, *, mode="append", operation_id=None):
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        if operation_id is None and mode == "replace-collection":
            active_collection_operation = self.manifests.read_snapshot().manifest.get("collection_operation_id")
            if active_collection_operation is not None:
                operation_id = active_collection_operation
        if operation_id is None and prior and (
            prior.get("pending_operation_id")
            and prior.get("pending_source_fingerprint") == fingerprint
        ):
            operation_id = prior["pending_operation_id"]
        if operation_id is None:
            generation = int(prior.get("document_generation", 0)) + 1 if prior else 1
            operation_id = f"ingest:{self.manifests.collection}:{document_id}:{generation}:{fingerprint}"
        return self.manifests.reserve(document_id, operation_id, fingerprint, mode=mode)

    def build_and_publish(
        self,
        chunks,
        embeddings,
        document_id,
        *,
        mode="append",
        operation_id=None,
        claim=None,
        qdrant=None,
        qdrant_claim_preparer=None,
        document_generation=None,
        **kwargs,
    ):
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        generation = claim.get("document_generation") if claim else (
            document_generation if document_generation is not None else (
                int(prior.get("document_generation", 0)) + 1 if prior else 1
            )
        )
        if operation_id is None and prior and (
            prior.get("pending_operation_id")
            and prior.get("pending_source_fingerprint") == fingerprint
        ):
            operation_id = prior["pending_operation_id"]
        if operation_id is None:
            operation_id = f"ingest:{self.manifests.collection}:{document_id}:{generation}:{fingerprint}"
        if claim is not None and (
            claim.get("document_id") != document_id
            or claim.get("source_fingerprint") != fingerprint
            or claim.get("operation_id") != operation_id
            or (
                document_generation is not None
                and claim.get("document_generation") != document_generation
            )
        ):
            raise GraphLifecycleError("caller inputs do not match the persisted graph claim")
        claim = claim or self.manifests.reserve(
            document_id,
            operation_id,
            fingerprint,
            mode=mode,
            document_generation=document_generation,
        )

        def verify_qdrant_claim() -> None:
            if qdrant is None:
                return
            verifier = getattr(qdrant, "verify_graph_claim_current", None)
            if not callable(verifier):
                raise RuntimeError(
                    "Qdrant cannot validate the graph claim before graph publication"
                )
            verifier(claim)

        def prepare_qdrant_claim() -> None:
            if qdrant is None or qdrant_claim_preparer is None:
                return
            preparer = getattr(qdrant, qdrant_claim_preparer, None)
            if not callable(preparer):
                raise RuntimeError(
                    f"Qdrant cannot prepare {qdrant_claim_preparer} before graph publication"
                )
            preparer(self.manifests, claim)

        try:
            prepare_qdrant_claim()
            graph, details = build_document_graph(chunks, embeddings, document_id, **kwargs)
            canonical = serialize_graph(
                graph,
                chunks,
                document_id,
                claim["document_generation"],
                details["raw_evidence"],
                details["diagnostics"],
                details.get("active_evidence"),
            )
            artifact_key, digest = self.artifacts.write(claim, canonical)
            # Read-back validates gzip, immutable bytes, metadata, and digest
            # before the manifest's active pointer is changed.
            self.artifacts.read(
                artifact_key,
                digest,
                claim.get("pending_backend") or claim.get("backend"),
                claim["document_generation"],
                claim["source_fingerprint"],
            )
            if qdrant is not None:
                verify_qdrant_claim()
                self.manifests.assert_claim_current(claim)
            self.manifests.bind_artifact(claim, artifact_key, digest)
            if qdrant is not None:
                verify_qdrant_claim()
                self.manifests.assert_claim_current(claim)
                verify_tombstones = getattr(qdrant, "verify_collection_tombstone_proof", None)
                if callable(verify_tombstones):
                    verify_tombstones(self.manifests)
            entry = self.manifests.publish(claim, artifact_key, digest)
            return {"status": entry["status"], "entry": entry, "artifact_key": artifact_key, "artifact_digest": digest, "details": details}
        except Exception as exc:
            try:
                failure_reason = f"{type(exc).__name__}: {exc}"
                claim_is_stale = False
                if qdrant is not None:
                    try:
                        verify_qdrant_claim()
                    except Exception as qdrant_exc:
                        claim_is_stale = True
                        failure_reason = f"{failure_reason}; Qdrant validation: {qdrant_exc}"
                self.manifests.assert_claim_current(claim)
                entry = self.manifests.stale(claim, failure_reason) if claim_is_stale else self.manifests.fail(claim, failure_reason)
            except Exception as fail_exc:
                raise GraphLifecycleError("graph failure status CAS failed; claim remains fail-closed") from fail_exc
            return {"status": entry.get("status", "unavailable"), "entry": entry, "failure_reason": str(exc)}

    def backfill(
        self,
        chunks,
        embeddings,
        document_id,
        *,
        document_generation=None,
        qdrant=None,
        **kwargs,
    ):
        """Backfill uses payloads and stored vectors; it never re-embeds text."""
        if (
            isinstance(document_generation, bool)
            or not isinstance(document_generation, int)
            or document_generation <= 0
        ):
            return {
                "status": "unavailable",
                "failure_reason": "document generation metadata is incomplete or inconsistent; rebuild required",
            }
        fingerprint = source_fingerprint(chunks, document_id)
        prior = self.manifests.get(document_id)
        if prior and prior.get("status") == "tombstoned":
            return {
                "status": "unavailable",
                "entry": prior,
                "failure_reason": "document is tombstoned; rebuild or re-ingest with replace-document required",
            }
        if prior:
            prior_generation = prior.get("document_generation")
            if (
                isinstance(prior_generation, bool)
                or not isinstance(prior_generation, int)
                or prior_generation != document_generation
            ):
                return {
                    "status": "unavailable",
                    "entry": prior,
                    "failure_reason": "manifest document generation conflicts with Qdrant; rebuild required",
                }
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
            qdrant=qdrant,
            qdrant_claim_preparer="materialize_backfill_claim",
            document_generation=document_generation,
            **kwargs,
        )


def backfill_qdrant_collection(qdrant, collection: str, *, object_store=None, document_id: str | None = None, **kwargs) -> list[dict]:
    """Build graph artifacts from existing payloads; no embedding call is made."""
    try:
        chunks = qdrant.scroll_document_chunks(document_id=document_id, include_vectors=True)
    except ValueError:
        return [{
            "status": "unavailable",
            "document_id": None,
            "failure_reason": "legacy Qdrant payload cannot be backfilled; rebuild required",
        }]

    grouped = {}
    results = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            results.append({
                "status": "unavailable",
                "document_id": None,
                "failure_reason": "Qdrant payload is malformed; rebuild required",
            })
            continue
        current_document_id = chunk.get("document_id")
        if not isinstance(current_document_id, str) or not current_document_id.strip():
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "document identity metadata is incomplete; rebuild required",
            })
            continue
        grouped.setdefault(current_document_id, []).append(chunk)

    def valid_stored_vector(vector: Any) -> bool:
        if not isinstance(vector, (list, tuple)) or not vector:
            return False
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                if not math.isfinite(value):
                    return False
            except OverflowError:
                return False
        return True

    pipeline = None
    for current_document_id, document_chunks in sorted(grouped.items(), key=lambda item: str(item[0])):
        if any(
            not isinstance(chunk.get("chunk_uid"), str)
            or not chunk["chunk_uid"].strip()
            or isinstance(chunk.get("chunk_id"), bool)
            or not isinstance(chunk.get("chunk_id"), int)
            for chunk in document_chunks
        ):
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "chunk identity metadata is incomplete; rebuild required",
            })
            continue
        if any(chunk.get("vector_point") is not True for chunk in document_chunks):
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "vector metadata is incomplete or inconsistent; replace-document rebuild required",
            })
            continue
        generations = [chunk.get("document_generation") for chunk in document_chunks]
        if (
            any(
                isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation <= 0
                for generation in generations
            )
            or len(set(generations)) != 1
        ):
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "document generation metadata is incomplete or inconsistent; rebuild required",
            })
            continue
        vectors = [chunk.get("_embedding") for chunk in document_chunks]
        if (
            not all(valid_stored_vector(vector) for vector in vectors)
            or len({len(vector) for vector in vectors}) != 1
        ):
            results.append({
                "status": "unavailable",
                "document_id": current_document_id,
                "failure_reason": "stored vectors are incomplete, invalid, or inconsistent; rebuild required",
            })
            continue
        if pipeline is None:
            pipeline = PersistentGraphPipeline(collection, object_store=object_store)
        results.append(
            pipeline.backfill(
                document_chunks,
                vectors,
                current_document_id,
                document_generation=generations[0],
                qdrant=qdrant,
                **kwargs,
            )
        )
    return results
