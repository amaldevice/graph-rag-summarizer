# ============================================================
# DOCLING LOADER
# Load PDF, extract text, simpan page metadata,
# dan render/upload image hanya bila diperlukan
# ============================================================

import os
import re
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

    def _infer_level(self, element, text: str) -> str:
        name = type(element).__name__.lower()
        if "section" in name or "heading" in name or "title" in name:
            return "section"
        if "table" in name:
            return "table"
        if "picture" in name or "figure" in name:
            return "figure"
        if len(self._sentence_parts(text)) > 1:
            return "paragraph"
        if len(text.split()) <= 30 and text.endswith((".", "?", "!")):
            return "sentence"
        return "paragraph"

    def _sentence_parts(self, text: str) -> list[str]:
        # ponytail: tiny sentence splitter; replace with NLP segmentation if sentence quality matters.
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
        return parts if len(parts) > 1 else [text.strip()]

    def _path_items(self, *items: str | None) -> list[str]:
        return [item for item in items if item is not None]

    def _chunk_payload(
        self,
        chunk_id: int,
        text: str,
        level: str,
        source_name: str,
        page_no,
        section: str | None,
        paragraph_index: int | None,
        sentence_index: int | None = None,
        section_id: str | None = None,
        paragraph_id: str | None = None,
        parent_id: str | None = None,
        parent_chunk_id: int | None = None,
        path: list[str] | None = None,
        context_only: bool = False,
    ) -> dict:
        hierarchy_path = list(path or [])
        payload = {
            "chunk_id": chunk_id,
            "text": text.strip(),
            "level": level,
            "hierarchy": {
                "level": level,
                "section": section,
                "section_id": section_id,
                "paragraph_index": paragraph_index,
                "sentence_index": sentence_index,
                "paragraph_id": paragraph_id,
                "parent_id": parent_id,
                "parent_chunk_id": parent_chunk_id,
                "path": hierarchy_path,
            },
            "layout": {
                "kind": level,
                "page_no": page_no,
            },
            "source": source_name,
            "page_no": page_no,
            "image_url": None,
        }
        if context_only:
            payload["context_only"] = True
        return payload

    def chunk_text(self, doc_result, source_name: str = "docling"):
        chunks = []
        chunk_id = 0
        paragraph_index = 0
        section_index = 0
        current_section = None
        current_section_id = None
        current_section_chunk_id = None

        for element, _level in doc_result.document.iterate_items():
            text = getattr(element, "text", None)
            if not text or not text.strip():
                continue

            page_no = getattr(element, "page_no", None)
            if page_no is None:
                prov = getattr(element, "prov", None)
                if prov and len(prov) > 0:
                    page_no = getattr(prov[0], "page_no", None)

            level = self._infer_level(element, text.strip())
            if level == "section":
                section_index += 1
                current_section = text.strip()
                current_section_id = f"section:{section_index}"
                current_section_chunk_id = chunk_id

            if level == "paragraph":
                paragraph_index += 1
                paragraph_id = f"paragraph:{paragraph_index}"
                paragraph_chunk_id = chunk_id
                paragraph_path = self._path_items(current_section_id, paragraph_id)
                chunks.append(self._chunk_payload(
                    paragraph_chunk_id,
                    text,
                    "paragraph",
                    source_name,
                    page_no,
                    current_section,
                    paragraph_index,
                    section_id=current_section_id,
                    paragraph_id=paragraph_id,
                    parent_id=current_section_id,
                    parent_chunk_id=current_section_chunk_id,
                    path=paragraph_path,
                ))
                chunk_id += 1
                for sentence_index, sentence in enumerate(self._sentence_parts(text), start=1):
                    if sentence == text.strip():
                        continue
                    chunks.append(self._chunk_payload(
                        chunk_id,
                        sentence,
                        "sentence",
                        source_name,
                        page_no,
                        current_section,
                        paragraph_index,
                        sentence_index,
                        section_id=current_section_id,
                        paragraph_id=paragraph_id,
                        parent_id=paragraph_id,
                        parent_chunk_id=paragraph_chunk_id,
                        path=paragraph_path + [f"sentence:{sentence_index}"],
                    ))
                    chunk_id += 1
                continue

            if level == "sentence":
                paragraph_index += 1
                paragraph_id = f"paragraph:{paragraph_index}"
                paragraph_chunk_id = chunk_id
                sentence_path = self._path_items(current_section_id, paragraph_id, "sentence:1")
                chunks.append(self._chunk_payload(
                    paragraph_chunk_id,
                    text,
                    "paragraph",
                    source_name,
                    page_no,
                    current_section,
                    paragraph_index,
                    section_id=current_section_id,
                    paragraph_id=paragraph_id,
                    parent_id=current_section_id,
                    parent_chunk_id=current_section_chunk_id,
                    path=self._path_items(current_section_id, paragraph_id),
                    context_only=True,
                ))
                chunk_id += 1
                chunks.append(self._chunk_payload(
                    chunk_id,
                    text,
                    level,
                    source_name,
                    page_no,
                    current_section,
                    paragraph_index,
                    1,
                    section_id=current_section_id,
                    paragraph_id=paragraph_id,
                    parent_id=paragraph_id,
                    parent_chunk_id=paragraph_chunk_id,
                    path=sentence_path,
                ))
                chunk_id += 1
                continue

            chunks.append(self._chunk_payload(
                chunk_id,
                text,
                level,
                source_name,
                page_no,
                current_section,
                paragraph_index if level != "section" else None,
                section_id=current_section_id,
                parent_id=current_section_id if level != "section" else None,
                parent_chunk_id=current_section_chunk_id if level != "section" else None,
                path=([current_section_id] if level == "section" and current_section_id else
                    self._path_items(current_section_id, f"{level}:{chunk_id}")),
            ))
            chunk_id += 1

        if not chunks:
            print("⚠️ iterate_items kosong, fallback ke split markdown...")
            full_text = self.extract_text(doc_result)
            raw_chunks = [c.strip() for c in full_text.split("\n\n") if c.strip()]
            chunks = [
                self._chunk_payload(
                    idx,
                    chunk,
                    "paragraph",
                    source_name,
                    None,
                    None,
                    idx + 1,
                    paragraph_id=f"paragraph:{idx + 1}",
                    path=[f"paragraph:{idx + 1}"],
                )
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
