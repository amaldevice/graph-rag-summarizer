# ============================================================
# EMBEDDER
# Ubah text chunk menjadi vector embedding
# ============================================================

from sentence_transformers import SentenceTransformer
from config.settings import EMBEDDING_MODEL


class TextEmbedder:
    def __init__(self):
        print(f"🔄 Memuat model embedding: {EMBEDDING_MODEL}")
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        print("✅ Model embedding siap")

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