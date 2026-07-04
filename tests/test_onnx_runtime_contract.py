import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from embedding.runtime_resolver import (
    ONNX_BACKEND,
    SENTENCE_TRANSFORMERS_BACKEND,
    resolve_embedding_runtime,
)


DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"


def test_onnx_runtime_stays_on_the_same_model_when_it_falls_back(tmp_path: Path) -> None:
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

    assert decision.model_name == DEFAULT_MODEL
    assert decision.resolved_backend == SENTENCE_TRANSFORMERS_BACKEND
    assert decision.fallback_reason is not None


def test_onnx_runtime_downgrades_to_cpu_even_when_mps_was_requested(tmp_path: Path) -> None:
    decision = resolve_embedding_runtime(
        model_name=DEFAULT_MODEL,
        requested_backend="onnx",
        requested_device="mps",
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
    assert decision.fallback_reason is not None
    assert "CPU only" in decision.fallback_reason


def test_onnx_runtime_uses_the_project_local_onnx_cache_root(tmp_path: Path) -> None:
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
        onnx_support_available=True,
    )

    assert decision.cache_folder == tmp_path / ".cache" / "embedding" / "onnx"
