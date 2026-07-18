import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from embedding.runtime_resolver import (
    ONNX_BACKEND,
    SENTENCE_TRANSFORMERS_BACKEND,
    onnx_dependencies_available,
    resolve_embedding_runtime,
)


DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"


def test_resolver_prefers_mps_on_macos_when_available(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="sentence-transformers",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Darwin",
        mps_available=True,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.detected_platform == "macos"
    assert decision.resolved_backend == SENTENCE_TRANSFORMERS_BACKEND
    assert decision.resolved_device == "mps"
    assert decision.fallback_reason is None
    assert decision.cache_folder == tmp_path / ".cache" / "embedding" / "models"


def test_resolver_falls_back_to_cpu_on_macos_when_mps_is_unavailable(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="sentence-transformers",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Darwin",
        mps_available=False,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_device == "cpu"
    assert decision.fallback_reason is not None
    assert "fell back to CPU" in decision.fallback_reason


def test_resolver_keeps_windows_and_linux_without_cuda_on_cpu_by_default(tmp_path: Path) -> None:
    for system_name in ("Windows", "Linux"):
        decision = resolve_embedding_runtime(
            model_name=DEFAULT_MODEL,
            requested_backend="sentence-transformers",
            requested_device="auto",
            onnx_allowed_models=[DEFAULT_MODEL],
            local_files_only=False,
            project_root=tmp_path,
            system_name=system_name,
            mps_available=False,
            cuda_available=False,
            supports_backend_parameter=True,
            onnx_support_available=True,
        )

        assert decision.resolved_device == "cpu"
        assert decision.fallback_reason is None


def test_resolver_uses_cuda_for_linux_auto_when_available(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="sentence-transformers",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Linux",
        mps_available=False,
        cuda_available=True,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_device == "cuda"
    assert decision.fallback_reason is None


def test_resolver_downgrades_explicit_cuda_when_unavailable(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="sentence-transformers",
        requested_device="cuda",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Linux",
        mps_available=False,
        cuda_available=False,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_device == "cpu"
    assert decision.fallback_reason is not None
    assert "CUDA was requested" in decision.fallback_reason


def test_resolver_downgrades_explicit_mps_request_outside_macos(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="sentence-transformers",
        requested_device="mps",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Linux",
        mps_available=False,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_device == "cpu"
    assert decision.fallback_reason is not None
    assert "macOS" in decision.fallback_reason


def test_resolver_rejects_invalid_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported EMBEDDING_BACKEND"):
        resolve_embedding_runtime(
            model_name=DEFAULT_MODEL,
            requested_backend="invalid",
            requested_device="auto",
            onnx_allowed_models=[DEFAULT_MODEL],
            local_files_only=False,
        )


def test_resolver_rejects_invalid_device() -> None:
    with pytest.raises(ValueError, match="Unsupported EMBEDDING_DEVICE"):
        resolve_embedding_runtime(
            model_name=DEFAULT_MODEL,
            requested_backend="sentence-transformers",
            requested_device="gpu",
            onnx_allowed_models=[DEFAULT_MODEL],
            local_files_only=False,
        )


def test_resolver_allows_onnx_for_the_allowlisted_model(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="onnx",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Darwin",
        mps_available=True,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_backend == ONNX_BACKEND
    assert decision.resolved_device == "cpu"
    assert decision.sentence_transformer_backend == "onnx"
    assert decision.model_kwargs == {
        "export": True,
        "provider": "CPUExecutionProvider",
    }
    assert decision.cache_folder == tmp_path / ".cache" / "embedding" / "onnx"


def test_resolver_falls_back_from_onnx_when_model_is_not_allowlisted(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        requested_backend="onnx",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Linux",
        mps_available=False,
        supports_backend_parameter=True,
        onnx_support_available=True,
    )

    assert decision.resolved_backend == SENTENCE_TRANSFORMERS_BACKEND
    assert decision.model_name == "sentence-transformers/all-MiniLM-L6-v2"
    assert decision.fallback_reason is not None
    assert "allowlist" in decision.fallback_reason


def test_resolver_falls_back_from_onnx_when_optional_dependencies_are_missing(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="onnx",
        requested_device="auto",
        onnx_allowed_models=[DEFAULT_MODEL],
        local_files_only=False,
        project_root=tmp_path,
        system_name="Linux",
        mps_available=False,
        supports_backend_parameter=True,
        onnx_support_available=False,
    )

    assert decision.resolved_backend == SENTENCE_TRANSFORMERS_BACKEND
    assert decision.model_name == DEFAULT_MODEL
    assert decision.fallback_reason is not None
    assert "optional ONNX dependency group" in decision.fallback_reason or "ONNX dependencies" in decision.fallback_reason


def test_onnx_dependency_probe_returns_false_when_optimum_is_absent(monkeypatch) -> None:
    def fake_find_spec(module_name: str):
        if module_name == "optimum.onnxruntime":
            raise ModuleNotFoundError("optimum")
        return object()

    monkeypatch.setattr("embedding.runtime_resolver.importlib.util.find_spec", fake_find_spec)

    assert onnx_dependencies_available() is False
