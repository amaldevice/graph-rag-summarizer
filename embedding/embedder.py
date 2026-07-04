# ============================================================
# EMBEDDER
# Ubah text chunk menjadi vector embedding
# ============================================================

from dataclasses import replace

from sentence_transformers import SentenceTransformer

from config import settings
from embedding.runtime_resolver import (
    SENTENCE_TRANSFORMERS_BACKEND,
    resolve_embedding_runtime,
)

ONNX_FALLBACK_EXCEPTIONS = (
    ImportError,
    OSError,
    RuntimeError,
    ValueError,
)


class TextEmbedder:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.runtime = resolve_embedding_runtime(
            model_name=self.model_name,
            requested_backend=settings.EMBEDDING_BACKEND,
            requested_device=settings.EMBEDDING_DEVICE,
            onnx_allowed_models=settings.EMBEDDING_ONNX_ALLOWED_MODELS,
            local_files_only=settings.EMBEDDING_LOCAL_FILES_ONLY,
        )

        print(f"🔄 Memuat model embedding: {self.model_name}")
        print(
            "   Runtime requested : "
            f"backend={self.runtime.requested_backend}, device={self.runtime.requested_device}"
        )
        print(f"   Runtime detected  : platform={self.runtime.detected_platform}")
        print(
            "   Runtime resolved  : "
            f"backend={self.runtime.resolved_backend}, device={self.runtime.resolved_device}"
        )
        if self.runtime.fallback_reason:
            print(f"   Runtime fallback  : {self.runtime.fallback_reason}")
        if (
            settings.EMBEDDING_TRUST_REMOTE_CODE
            and self.model_name not in settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS
        ):
            print(
                "   Runtime note      : trust_remote_code stayed disabled because this model is outside the configured allowlist."
            )

        self.model = self._load_model()
        print("✅ Model embedding siap")

    def _load_model(self):
        try:
            return SentenceTransformer(self.model_name, **self._build_model_kwargs())
        except ONNX_FALLBACK_EXCEPTIONS as exc:
            if self.runtime.resolved_backend != "onnx":
                raise

            self.runtime = self._build_sentence_transformers_fallback_runtime(exc)
            print(f"   Runtime fallback  : {self.runtime.fallback_reason}")
            print(
                "   Runtime resolved  : "
                f"backend={self.runtime.resolved_backend}, device={self.runtime.resolved_device}"
            )
            return SentenceTransformer(self.model_name, **self._build_model_kwargs())

    def _build_model_kwargs(self):
        model_kwargs = {
            "device": self.runtime.resolved_device,
            "cache_folder": str(self.runtime.cache_folder),
            "local_files_only": self.runtime.local_files_only,
            "trust_remote_code": self._should_trust_remote_code(),
        }
        if self.runtime.sentence_transformer_backend:
            model_kwargs["backend"] = self.runtime.sentence_transformer_backend
        if self.runtime.model_kwargs:
            model_kwargs["model_kwargs"] = dict(self.runtime.model_kwargs)
        return model_kwargs

    def _build_sentence_transformers_fallback_runtime(self, exc: Exception):
        fallback_runtime = resolve_embedding_runtime(
            model_name=self.model_name,
            requested_backend=SENTENCE_TRANSFORMERS_BACKEND,
            requested_device=settings.EMBEDDING_DEVICE,
            onnx_allowed_models=settings.EMBEDDING_ONNX_ALLOWED_MODELS,
            local_files_only=settings.EMBEDDING_LOCAL_FILES_ONLY,
        )
        combined_reason = " ".join(
            part
            for part in (
                self.runtime.fallback_reason,
                f"ONNX initialization failed: {exc}. Falling back to sentence-transformers.",
            )
            if part
        )
        return replace(fallback_runtime, fallback_reason=combined_reason)

    def _should_trust_remote_code(self) -> bool:
        return (
            settings.EMBEDDING_TRUST_REMOTE_CODE
            and self.model_name in settings.EMBEDDING_TRUST_REMOTE_CODE_ALLOWED_MODELS
        )

    # ========================================================
    # EMBED SATU TEKS
    # Input : string text
    # Output: list vector
    # ========================================================
    def embed_text(self, text: str):
        vector = self.model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    # ========================================================
    # EMBED BANYAK CHUNK
    # Input : list of dict [{'chunk_id':.., 'text':..}, ...]
    # Output: list vector
    # ========================================================
    def embed_chunks(self, chunks: list):
        texts = [chunk["text"] for chunk in chunks]
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
        return vectors.tolist()
