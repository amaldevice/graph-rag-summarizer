from __future__ import annotations

import importlib.util
import inspect
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from embedding.cache_paths import (
    get_onnx_cache_dir,
    get_sentence_transformers_cache_dir,
)


SENTENCE_TRANSFORMERS_BACKEND = "sentence-transformers"
ONNX_BACKEND = "onnx"
CPU_DEVICE = "cpu"
MPS_DEVICE = "mps"
CUDA_DEVICE = "cuda"
AUTO_DEVICE = "auto"


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeDecision:
    model_name: str
    requested_backend: str
    requested_device: str
    detected_platform: str
    resolved_backend: str
    resolved_device: str
    cache_folder: Path
    local_files_only: bool
    fallback_reason: str | None = None
    sentence_transformer_backend: str | None = None
    model_kwargs: dict[str, Any] = field(default_factory=dict)


def normalize_backend(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "default": SENTENCE_TRANSFORMERS_BACKEND,
        "sentence_transformers": SENTENCE_TRANSFORMERS_BACKEND,
        "torch": SENTENCE_TRANSFORMERS_BACKEND,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {SENTENCE_TRANSFORMERS_BACKEND, ONNX_BACKEND}:
        raise ValueError(
            "Unsupported EMBEDDING_BACKEND. Expected 'sentence-transformers' or 'onnx'."
        )
    return normalized


def normalize_device(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {AUTO_DEVICE, CPU_DEVICE, MPS_DEVICE, CUDA_DEVICE}:
        raise ValueError("Unsupported EMBEDDING_DEVICE. Expected 'auto', 'cpu', 'mps', or 'cuda'.")
    return normalized


def detect_platform(system_name: str | None = None) -> str:
    normalized = (system_name or platform.system()).strip().lower()
    if normalized == "darwin":
        return "macos"
    if normalized == "windows":
        return "windows"
    if normalized == "linux":
        return "linux"
    return normalized or "unknown"


def sentence_transformer_supports_backend() -> bool:
    from sentence_transformers import SentenceTransformer

    return "backend" in inspect.signature(SentenceTransformer.__init__).parameters


def onnx_dependencies_available() -> bool:
    return _module_available("optimum.onnxruntime") and _module_available("onnxruntime")


def is_mps_available() -> bool:
    try:
        import torch
    except Exception:
        return False

    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    if mps_backend is None or not hasattr(mps_backend, "is_available"):
        return False
    return bool(mps_backend.is_available())


def is_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False

    cuda = getattr(torch, "cuda", None)
    return bool(cuda and hasattr(cuda, "is_available") and cuda.is_available())


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def resolve_embedding_runtime(
    *,
    model_name: str,
    requested_backend: str,
    requested_device: str,
    onnx_allowed_models: Iterable[str],
    local_files_only: bool,
    project_root: Path | None = None,
    system_name: str | None = None,
    mps_available: bool | None = None,
    cuda_available: bool | None = None,
    supports_backend_parameter: bool | None = None,
    onnx_support_available: bool | None = None,
) -> EmbeddingRuntimeDecision:
    backend = normalize_backend(requested_backend)
    device = normalize_device(requested_device)
    detected_platform = detect_platform(system_name)
    allowed_models = {item.strip() for item in onnx_allowed_models if item.strip()}

    supports_backend = (
        sentence_transformer_supports_backend()
        if supports_backend_parameter is None
        else supports_backend_parameter
    )
    has_onnx_support = (
        onnx_dependencies_available()
        if onnx_support_available is None
        else onnx_support_available
    )
    can_use_mps = (
        is_mps_available() if mps_available is None and detected_platform == "macos" else bool(mps_available)
    )
    can_use_cuda = (
        is_cuda_available() if cuda_available is None and detected_platform == "linux" else bool(cuda_available)
    )

    fallback_reasons: list[str] = []

    if backend == ONNX_BACKEND:
        if model_name not in allowed_models:
            fallback_reasons.append(
                f"ONNX is limited to the allowlist in this project. '{model_name}' fell back to sentence-transformers."
            )
        elif not supports_backend:
            fallback_reasons.append(
                "The installed sentence-transformers build does not support backend='onnx'; falling back to sentence-transformers."
            )
        elif not has_onnx_support:
            fallback_reasons.append(
                "ONNX dependencies are not installed. Run the optional ONNX dependency group, then retry."
            )
        else:
            if device not in {AUTO_DEVICE, CPU_DEVICE}:
                fallback_reasons.append(
                    "ONNX currently runs on CPU only in this project, so the requested device was downgraded to CPU."
                )
            return EmbeddingRuntimeDecision(
                model_name=model_name,
                requested_backend=backend,
                requested_device=device,
                detected_platform=detected_platform,
                resolved_backend=ONNX_BACKEND,
                resolved_device=CPU_DEVICE,
                cache_folder=get_onnx_cache_dir(project_root),
                local_files_only=local_files_only,
                fallback_reason=" ".join(fallback_reasons) or None,
                sentence_transformer_backend=ONNX_BACKEND,
                model_kwargs={
                    "export": True,
                    "provider": "CPUExecutionProvider",
                },
            )

    resolved_device, device_fallback_reason = resolve_sentence_transformers_device(
        detected_platform=detected_platform,
        requested_device=device,
        mps_available=can_use_mps,
        cuda_available=can_use_cuda,
    )
    if device_fallback_reason:
        fallback_reasons.append(device_fallback_reason)

    return EmbeddingRuntimeDecision(
        model_name=model_name,
        requested_backend=backend,
        requested_device=device,
        detected_platform=detected_platform,
        resolved_backend=SENTENCE_TRANSFORMERS_BACKEND,
        resolved_device=resolved_device,
        cache_folder=get_sentence_transformers_cache_dir(project_root),
        local_files_only=local_files_only,
        fallback_reason=" ".join(fallback_reasons) or None,
    )


def resolve_sentence_transformers_device(
    *,
    detected_platform: str,
    requested_device: str,
    mps_available: bool,
    cuda_available: bool,
) -> tuple[str, str | None]:
    if requested_device == CPU_DEVICE:
        return CPU_DEVICE, None

    if requested_device == MPS_DEVICE:
        if detected_platform != "macos":
            return CPU_DEVICE, "MPS is only supported on macOS in this project, so the runtime fell back to CPU."
        if not mps_available:
            return CPU_DEVICE, "MPS was requested but is unavailable on this macOS host, so the runtime fell back to CPU."
        return MPS_DEVICE, None

    if requested_device == CUDA_DEVICE:
        if detected_platform != "linux" or not cuda_available:
            return CPU_DEVICE, "CUDA was requested but is unavailable on this host, so the runtime fell back to CPU."
        return CUDA_DEVICE, None

    if detected_platform == "macos":
        if mps_available:
            return MPS_DEVICE, None
        return CPU_DEVICE, "MPS is unavailable on this macOS host, so the runtime fell back to CPU."

    if detected_platform == "linux" and cuda_available:
        return CUDA_DEVICE, None

    return CPU_DEVICE, None
