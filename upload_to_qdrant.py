# ============================================================
# UPLOAD TO QDRANT
# PDF -> Docling -> Chunk -> Embedding -> Qdrant
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import os

from config.settings import QDRANT_COLLECTION
from launcher.contract import (
    DEFAULT_INGEST_MODE,
    resolve_ingest_mode,
    resolve_profile,
    suggest_collection_from_pdf,
    suggest_document_id_from_pdf,
)
from launcher.runners import run_ingest


def _build_legacy_ingest_config() -> dict:
    pdf_path = os.getenv("PDF_PATH", "sample.pdf")
    collection = os.getenv("QDRANT_COLLECTION", QDRANT_COLLECTION).strip()
    if not collection:
        collection = suggest_collection_from_pdf(pdf_path)
    document_id = os.getenv("DOCUMENT_ID", "").strip() or suggest_document_id_from_pdf(pdf_path)
    ingest_mode = resolve_ingest_mode(os.getenv("INGEST_MODE", DEFAULT_INGEST_MODE))

    return {
        "mode": "ingest",
        "profile": resolve_profile(None, os.getenv("LAUNCHER_PROFILE", "") or None),
        "collection": collection,
        "query": "",
        "retrieval_limit": 0,
        "pdf_path": pdf_path,
        "ingest_mode": ingest_mode,
        "document_id": document_id,
        "json_output": "",
        "confirm_existing_collection": True,
    }


def main():
    print("\n=== UPLOAD MODE ===")
    run_ingest(_build_legacy_ingest_config())


if __name__ == "__main__":
    main()
