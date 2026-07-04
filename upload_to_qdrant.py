# ============================================================
# UPLOAD TO QDRANT
# PDF -> Docling -> Chunk -> Embedding -> Qdrant
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import os

from preprocessing.docling_loader import DoclingLoader
from embedding.embedder import TextEmbedder
from vectordb.qdrant_handler import QdrantHandler


def main():
    pdf_path = os.getenv("PDF_PATH", "sample.pdf")

    print("\n=== UPLOAD MODE ===")
    print(f"PDF_PATH : {pdf_path}")

    loader = DoclingLoader()
    result = loader.process_pdf(pdf_path)
    chunks = result["chunks"]
    if not chunks:
        raise ValueError("Tidak ada chunk yang berhasil diekstrak dari dokumen.")

    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    qdrant = QdrantHandler()
    qdrant.create_collection_if_not_exists(vector_size=len(vectors[0]))
    qdrant.upsert_chunks(chunks, vectors)

    print("\n=== UPLOAD DONE ===")
    print(f"Total chunks uploaded : {len(chunks)}")
    print(f"Collection            : {qdrant.collection_name}")
    print("Dokumen berhasil diproses dan disimpan ke Qdrant.")


if __name__ == "__main__":
    main()
