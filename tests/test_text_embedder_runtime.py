import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from embedding.runtime_resolver import EmbeddingRuntimeDecision
from embedding.embedder import TextEmbedder


class FakeEncodedValue:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


def test_text_embedder_uses_the_resolved_sentence_transformers_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="sentence-transformers",
        requested_device="auto",
        detected_platform="macos",
        resolved_backend="sentence-transformers",
        resolved_device="mps",
        cache_folder=tmp_path / ".cache" / "embedding" / "models",
        local_files_only=False,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

        def encode(self, payload, **kwargs):
            captured.setdefault("encode_calls", []).append((payload, kwargs))
            if isinstance(payload, str):
                return FakeEncodedValue([0.1, 0.2])
            return FakeEncodedValue([[0.1, 0.2], [0.3, 0.4]])

    monkeypatch.setattr("embedding.embedder.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr("embedding.embedder.resolve_embedding_runtime", lambda **_: decision)
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_MODEL", "custom-model")
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE", True)
    monkeypatch.setattr(
        "embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS",
        ["custom-model"],
    )

    embedder = TextEmbedder()

    assert captured["model_name"] == "custom-model"
    assert captured["kwargs"] == {
        "device": "mps",
        "cache_folder": str(decision.cache_folder),
        "local_files_only": False,
        "trust_remote_code": True,
    }
    assert embedder.embed_text("hello") == [0.1, 0.2]
    assert embedder.embed_chunks([{"text": "one"}, {"text": "two"}]) == [
        [0.1, 0.2],
        [0.3, 0.4],
    ]


def test_text_embedder_passes_onnx_backend_arguments_and_logs_fallback(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    captured: dict[str, object] = {}
    decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="onnx",
        requested_device="mps",
        detected_platform="macos",
        resolved_backend="onnx",
        resolved_device="cpu",
        cache_folder=tmp_path / ".cache" / "embedding" / "onnx",
        local_files_only=True,
        fallback_reason="ONNX currently runs on CPU only in this project.",
        sentence_transformer_backend="onnx",
        model_kwargs={
            "export": True,
            "provider": "CPUExecutionProvider",
        },
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

        def encode(self, payload, **kwargs):
            del payload, kwargs
            return FakeEncodedValue([0.1, 0.2])

    monkeypatch.setattr("embedding.embedder.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr("embedding.embedder.resolve_embedding_runtime", lambda **_: decision)
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_MODEL", "custom-model")
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE", True)
    monkeypatch.setattr(
        "embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS",
        ["custom-model"],
    )

    TextEmbedder()

    assert captured["kwargs"] == {
        "device": "cpu",
        "cache_folder": str(decision.cache_folder),
        "local_files_only": True,
        "trust_remote_code": True,
        "backend": "onnx",
        "model_kwargs": {
            "export": True,
            "provider": "CPUExecutionProvider",
        },
    }

    output = capsys.readouterr().out
    assert "backend=onnx" in output
    assert "device=cpu" in output
    assert "Runtime fallback" in output


def test_text_embedder_falls_back_to_sentence_transformers_when_onnx_init_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    onnx_decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="onnx",
        requested_device="auto",
        detected_platform="linux",
        resolved_backend="onnx",
        resolved_device="cpu",
        cache_folder=tmp_path / ".cache" / "embedding" / "onnx",
        local_files_only=False,
        sentence_transformer_backend="onnx",
        model_kwargs={
            "export": True,
            "provider": "CPUExecutionProvider",
        },
    )
    fallback_decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="sentence-transformers",
        requested_device="auto",
        detected_platform="linux",
        resolved_backend="sentence-transformers",
        resolved_device="cpu",
        cache_folder=tmp_path / ".cache" / "embedding" / "models",
        local_files_only=False,
    )
    decisions = iter([onnx_decision, fallback_decision])
    calls: list[dict[str, object]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            calls.append({"model_name": model_name, "kwargs": kwargs})
            if kwargs.get("backend") == "onnx":
                raise RuntimeError("unsupported architecture")

        def encode(self, payload, **kwargs):
            del payload, kwargs
            return FakeEncodedValue([0.1, 0.2])

    monkeypatch.setattr("embedding.embedder.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr("embedding.embedder.resolve_embedding_runtime", lambda **_: next(decisions))
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_MODEL", "custom-model")
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE", True)
    monkeypatch.setattr(
        "embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS",
        ["custom-model"],
    )

    embedder = TextEmbedder()

    assert len(calls) == 2
    assert calls[0]["kwargs"]["backend"] == "onnx"
    assert "backend" not in calls[1]["kwargs"]
    assert embedder.runtime.resolved_backend == "sentence-transformers"

    output = capsys.readouterr().out
    assert "ONNX initialization failed" in output


def test_text_embedder_disables_remote_code_for_models_outside_the_allowlist(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    captured: dict[str, object] = {}
    decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="sentence-transformers",
        requested_device="auto",
        detected_platform="linux",
        resolved_backend="sentence-transformers",
        resolved_device="cpu",
        cache_folder=tmp_path / ".cache" / "embedding" / "models",
        local_files_only=False,
    )

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

        def encode(self, payload, **kwargs):
            del payload, kwargs
            return FakeEncodedValue([0.1, 0.2])

    monkeypatch.setattr("embedding.embedder.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr("embedding.embedder.resolve_embedding_runtime", lambda **_: decision)
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_MODEL", "custom-model")
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE", True)
    monkeypatch.setattr(
        "embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS",
        ["nomic-ai/nomic-embed-text-v1.5"],
    )

    TextEmbedder()

    assert captured["kwargs"]["trust_remote_code"] is False
    assert "trust_remote_code stayed disabled" in capsys.readouterr().out


def test_text_embedder_reraises_unexpected_onnx_initialization_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    decision = EmbeddingRuntimeDecision(
        model_name="custom-model",
        requested_backend="onnx",
        requested_device="auto",
        detected_platform="linux",
        resolved_backend="onnx",
        resolved_device="cpu",
        cache_folder=tmp_path / ".cache" / "embedding" / "onnx",
        local_files_only=False,
        sentence_transformer_backend="onnx",
        model_kwargs={
            "export": True,
            "provider": "CPUExecutionProvider",
        },
    )
    calls = 0

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            nonlocal calls
            del model_name, kwargs
            calls += 1
            raise TypeError("unexpected constructor bug")

    monkeypatch.setattr("embedding.embedder.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr("embedding.embedder.resolve_embedding_runtime", lambda **_: decision)
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_MODEL", "custom-model")
    monkeypatch.setattr("embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE", False)
    monkeypatch.setattr(
        "embedding.embedder.settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS",
        ["custom-model"],
    )

    with pytest.raises(TypeError, match="unexpected constructor bug"):
        TextEmbedder()

    assert calls == 1
