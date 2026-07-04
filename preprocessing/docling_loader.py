# ============================================================
# DOCLING LOADER
# Load PDF, extract text, simpan page metadata,
# dan render/upload image hanya bila diperlukan
# ============================================================

import os
from pathlib import Path

from docling.document_converter import DocumentConverter

from config import settings
from preprocessing.image_exporter import DoclingImageExporter
from storage.factory import get_storage_handler


class DoclingLoader:
    def __init__(self):
        self.converter = DocumentConverter()
        self.storage_handler = get_storage_handler()
        self.image_exporter = DoclingImageExporter()

    def load_pdf(self, pdf_path: str):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"❌ File tidak ditemukan: {pdf_path}")
        print(f"📄 Memproses PDF: {pdf_path}")
        result = self.converter.convert(pdf_path)
        print("✅ PDF berhasil dikonversi oleh Docling")
        return result

    def extract_text(self, doc_result):
        return doc_result.document.export_to_markdown()

    def chunk_text(self, doc_result, source_name: str = "docling"):
        chunks = []
        chunk_id = 0

        for element, _level in doc_result.document.iterate_items():
            text = getattr(element, "text", None)
            if not text or not text.strip():
                continue

            page_no = getattr(element, "page_no", None)
            if page_no is None:
                prov = getattr(element, "prov", None)
                if prov and len(prov) > 0:
                    page_no = getattr(prov[0], "page_no", None)

            chunks.append({
                "chunk_id": chunk_id,
                "text": text.strip(),
                "level": type(element).__name__,
                "source": source_name,
                "page_no": page_no,
                "image_url": None,
            })
            chunk_id += 1

        if not chunks:
            print("⚠️ iterate_items kosong, fallback ke split markdown...")
            full_text = self.extract_text(doc_result)
            raw_chunks = [c.strip() for c in full_text.split("\n\n") if c.strip()]
            chunks = [
                {
                    "chunk_id": idx,
                    "text": chunk,
                    "level": "paragraph",
                    "source": source_name,
                    "page_no": None,
                    "image_url": None,
                }
                for idx, chunk in enumerate(raw_chunks)
            ]

        print(f"✅ Total chunks: {len(chunks)}")
        return chunks

    def extract_and_upload_images(self, doc_result, pdf_path: str, target_pages=None):
        doc_filename = Path(pdf_path).stem
        exported = self.image_exporter.export_images(
            doc_result,
            doc_filename,
            pdf_path=pdf_path,
            target_pages=target_pages,
        )
        return self._upload_exported_images(exported, doc_filename)

    def render_and_upload_pages_on_demand(self, pdf_path: str, target_pages):
        if not settings.ENABLE_ON_DEMAND_PAGE_RENDER:
            print("ℹ️ On-demand page render dinonaktifkan oleh konfigurasi.")
            return []

        doc_filename = Path(pdf_path).stem
        exported = self.image_exporter.render_pages_on_demand(
            pdf_path=pdf_path,
            doc_filename=doc_filename,
            target_pages=target_pages,
            dpi=settings.FALLBACK_RENDER_DPI,
            max_pages=settings.MAX_FALLBACK_PAGES,
        )
        return self._upload_exported_images(exported, doc_filename)

    def _upload_exported_images(self, exported: list, doc_filename: str):
        uploaded = []
        for item in exported:
            object_name = f"images/{doc_filename}/{Path(item['path']).name}"
            self.storage_handler.upload_local_path(item["path"], object_name=object_name)
            image_url = self.storage_handler.build_image_url(object_name)
            uploaded.append({
                "type": item["type"],
                "page": item["page"],
                "object_name": object_name,
                "image_url": image_url,
            })
        return uploaded

    def build_page_image_map(self, images: list) -> dict:
        page_map = {}
        for img in images:
            page = img.get("page")
            if page is not None and page not in page_map:
                page_map[page] = img["image_url"]
        return page_map

    def attach_image_urls_to_chunks(self, chunks: list, page_image_map: dict):
        for chunk in chunks:
            page_no = chunk.get("page_no")
            if page_no is not None and page_no in page_image_map:
                chunk["image_url"] = page_image_map[page_no]
        return chunks

    def process_pdf(self, pdf_path: str):
        doc_result = self.load_pdf(pdf_path)
        chunks = self.chunk_text(doc_result, source_name=Path(pdf_path).name)

        images = []
        page_image_map = {}

        if not settings.ENABLE_ON_DEMAND_PAGE_RENDER:
            images = self.extract_and_upload_images(doc_result, pdf_path)
            page_image_map = self.build_page_image_map(images)
            chunks = self.attach_image_urls_to_chunks(chunks, page_image_map)
        else:
            print("ℹ️ On-demand image mode aktif: skip export image saat preprocessing awal.")

        chunks_with_image = sum(1 for c in chunks if c.get("image_url"))
        print(f"🔗 Chunks dengan image_url: {chunks_with_image} / {len(chunks)}")

        return {
            "pdf_path": pdf_path,
            "doc_result": doc_result,
            "chunks": chunks,
            "images": images,
            "page_image_map": page_image_map,
            "total_chunks": len(chunks),
            "total_images": len(images),
        }
