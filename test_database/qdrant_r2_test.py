# ============================================================
# TEST QDRANT + R2
# Cek apakah query mengembalikan text + image_url + page_no
# ============================================================

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from preprocessing.docling_loader import DoclingLoader
from embedding.embedder import TextEmbedder
from vectordb.qdrant_handler import QdrantHandler

# ============================================================
# KONFIGURASI — sesuaikan nama PDF dan query kamu
# ============================================================
PDF_PATH = "sample.pdf"
QUERY    = "What is the main idea of the paper?"
TOP_K    = 5

def main():
    print("=" * 55)
    print("  TEST QDRANT + R2")
    print("=" * 55)

    # 1. Load & proses PDF
    loader = DoclingLoader()
    result = loader.process_pdf(PDF_PATH)
    chunks = result["chunks"]
    images = result["images"]

    print(f"\n📦 Total chunks  : {result['total_chunks']}")
    print(f"🖼️  Total images  : {result['total_images']}")
    print(f"🗺️  Page-image map: {result['page_image_map']}")

    # 2. Embedding
    embedder = TextEmbedder()
    vectors = embedder.embed_chunks(chunks)

    # 3. Simpan ke Qdrant
    qdrant = QdrantHandler()
    qdrant.create_collection_if_not_exists(vector_size=len(vectors[0]))
    qdrant.upsert_chunks(chunks, vectors)

    # 4. Query Qdrant
    print(f"\n🔍 Query: '{QUERY}'")
    query_vector = embedder.embed_text(QUERY)
    results = qdrant.search(query_vector, limit=TOP_K)

    # 5. Tampilkan hasil
    print(f"\n{'='*55}")
    print(f"  HASIL QUERY (top {TOP_K})")
    print(f"{'='*55}")

    rows = []
    for i, r in enumerate(results):
        text      = r.payload.get("text", "")
        image_url = r.payload.get("image_url") or (r.payload.get("image_urls") or [None])[0]
        page_no   = r.payload.get("page_no", r.payload.get("page"))
        score     = round(r.score, 4)

        print(f"\n[{i+1}] Score   : {score}")
        print(f"     Page    : {page_no}")
        print(f"     Text    : {text[:120]}...")
        print(f"     Image   : {image_url if image_url else '(tidak ada gambar)'}")

        rows.append({
            "rank": i + 1,
            "score": score,
            "page_no": page_no,
            "text": text,
            "image_url": image_url,
        })

    # 6. Simpan ke CSV
    out_path = Path("output/qdrant_r2_test_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\n✅ Hasil disimpan ke: {out_path}")

    # 7. Ringkasan
    chunks_with_url = sum(1 for r in rows if r["image_url"])
    print(f"\n📊 Ringkasan:")
    print(f"   Chunk dengan image_url : {chunks_with_url} / {len(rows)}")
    if chunks_with_url == 0:
        print("   ⚠️  Tidak ada image_url — cek apakah PyMuPDF terinstall:")
        print("       pip install pymupdf")
    else:
        print("   ✅ Image URL berhasil disimpan di Qdrant payload!")
        print("   Buka URL di browser untuk verifikasi gambar dari R2.")

if __name__ == "__main__":
    main()
