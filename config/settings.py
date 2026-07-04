# ============================================================
# CONFIG SETTINGS
# Ambil konfigurasi dari file .env
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- QDRANT ---
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "summarizer_docs")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "")

# --- EMBEDDING ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", 768))

# --- SPACY ---
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_sm")

# --- DOCLING IMAGE EXPORT ---
DOCLING_IMAGE_DIR = os.getenv("DOCLING_IMAGE_DIR", "output/images")
DOCLING_IMAGE_MODE = os.getenv("DOCLING_IMAGE_MODE", "local")

# Export page image bawaan Docling untuk semua halaman
EXPORT_PAGE_IMAGES = os.getenv("EXPORT_PAGE_IMAGES", "False").lower() == "true"

# Export image untuk PictureItem / TableItem dari Docling
EXPORT_EMBEDDED_IMAGES = os.getenv("EXPORT_EMBEDDED_IMAGES", "True").lower() == "true"

# Jika tidak ada image dari Docling, boleh fallback render halaman PDF
ENABLE_FALLBACK_RENDER = os.getenv("ENABLE_FALLBACK_RENDER", "False").lower() == "true"

# Batasi jumlah halaman saat fallback render agar tidak meledak untuk PDF besar
MAX_FALLBACK_PAGES = int(os.getenv("MAX_FALLBACK_PAGES", 5))

# DPI fallback render
FALLBACK_RENDER_DPI = int(os.getenv("FALLBACK_RENDER_DPI", 120))

# Jika True, image tidak diekstrak saat process_pdf awal.
# Image baru dirender/upload saat memang dibutuhkan berdasarkan page number.
ENABLE_ON_DEMAND_PAGE_RENDER = os.getenv("ENABLE_ON_DEMAND_PAGE_RENDER", "True").lower() == "true"
