# ============================================================
# IMAGE EXPORTER
# Export gambar Docling dengan kontrol jumlah output
# Default: tidak export page image semua halaman
# ============================================================

from pathlib import Path
from typing import Iterable, Optional, Set

from docling_core.types.doc import PictureItem, TableItem
from config import settings

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("⚠️ PyMuPDF tidak tersedia, fallback render page dinonaktifkan.")


class DoclingImageExporter:
    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or settings.DOCLING_IMAGE_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_images(
        self,
        conv_res,
        doc_filename: str,
        pdf_path: str = None,
        target_pages: Optional[Iterable[int]] = None,
        export_page_images: Optional[bool] = None,
        export_embedded_images: Optional[bool] = None,
        enable_fallback_render: Optional[bool] = None,
        max_fallback_pages: Optional[int] = None,
        dpi: Optional[int] = None,
    ):
        exported = []
        picture_counter = 0
        table_counter = 0
        skipped = 0

        target_pages = set(p for p in (target_pages or []) if p is not None)
        export_page_images = settings.EXPORT_PAGE_IMAGES if export_page_images is None else export_page_images
        export_embedded_images = settings.EXPORT_EMBEDDED_IMAGES if export_embedded_images is None else export_embedded_images
        enable_fallback_render = settings.ENABLE_FALLBACK_RENDER if enable_fallback_render is None else enable_fallback_render
        max_fallback_pages = settings.MAX_FALLBACK_PAGES if max_fallback_pages is None else max_fallback_pages
        dpi = settings.FALLBACK_RENDER_DPI if dpi is None else dpi

        if export_page_images:
            for page_no, page in conv_res.document.pages.items():
                if target_pages and page_no not in target_pages:
                    continue
                page_img = getattr(page, "image", None)
                if page_img is None:
                    continue
                pil_img = getattr(page_img, "pil_image", None)
                if pil_img is None:
                    skipped += 1
                    continue
                page_image_filename = self.output_dir / f"{doc_filename}-page-{page_no}.png"
                pil_img.save(page_image_filename, format="PNG")
                exported.append({
                    "type": "page",
                    "page": page_no,
                    "path": str(page_image_filename)
                })

        if export_embedded_images:
            for element, _level in conv_res.document.iterate_items():
                page_no = getattr(element, "page_no", None)
                if page_no is None:
                    prov = getattr(element, "prov", None)
                    if prov and len(prov) > 0:
                        page_no = getattr(prov[0], "page_no", None)

                if target_pages and page_no not in target_pages:
                    continue

                if isinstance(element, TableItem):
                    img = element.get_image(conv_res.document)
                    if img is None:
                        skipped += 1
                        continue
                    table_counter += 1
                    filename = self.output_dir / f"{doc_filename}-table-{table_counter}.png"
                    img.save(filename, "PNG")
                    exported.append({
                        "type": "table",
                        "page": page_no,
                        "path": str(filename)
                    })

                elif isinstance(element, PictureItem):
                    img = element.get_image(conv_res.document)
                    if img is None:
                        skipped += 1
                        continue
                    picture_counter += 1
                    filename = self.output_dir / f"{doc_filename}-picture-{picture_counter}.png"
                    img.save(filename, "PNG")
                    exported.append({
                        "type": "picture",
                        "page": page_no,
                        "path": str(filename)
                    })

        print(f"🖼️ Exported images: {len(exported)} | Skipped: {skipped}")

        if len(exported) == 0 and enable_fallback_render and pdf_path is not None and PYMUPDF_AVAILABLE:
            print("⚠️ Tidak ada image dari Docling, fallback render halaman terbatas...")
            fallback_exported = self._fallback_render_pages(
                pdf_path=pdf_path,
                doc_filename=doc_filename,
                target_pages=target_pages,
                max_pages=max_fallback_pages,
                dpi=dpi,
            )
            exported.extend(fallback_exported)
            print(f"✅ Fallback render: {len(fallback_exported)} halaman berhasil dirender")

        elif len(exported) == 0 and enable_fallback_render and not PYMUPDF_AVAILABLE:
            print("❌ PyMuPDF tidak tersedia, fallback render tidak bisa dijalankan.")
            print("   Install dengan: pip install pymupdf")

        return exported

    def render_pages_on_demand(
        self,
        pdf_path: str,
        doc_filename: str,
        target_pages: Iterable[int],
        dpi: Optional[int] = None,
        max_pages: Optional[int] = None,
    ):
        if not PYMUPDF_AVAILABLE:
            print("❌ PyMuPDF tidak tersedia, on-demand render tidak bisa dijalankan.")
            return []

        target_pages = sorted(set(p for p in target_pages if p is not None))
        if not target_pages:
            return []

        if max_pages is None:
            max_pages = settings.MAX_FALLBACK_PAGES
        if dpi is None:
            dpi = settings.FALLBACK_RENDER_DPI

        limited_pages = target_pages[:max_pages] if max_pages > 0 else target_pages
        return self._render_specific_pages(pdf_path, doc_filename, limited_pages, dpi=dpi)

    def _fallback_render_pages(
        self,
        pdf_path: str,
        doc_filename: str,
        target_pages: Optional[Set[int]] = None,
        max_pages: int = 5,
        dpi: int = 120,
    ):
        if target_pages:
            pages = sorted(target_pages)
            if max_pages > 0:
                pages = pages[:max_pages]
            return self._render_specific_pages(pdf_path, doc_filename, pages, dpi=dpi)

        fallback_exported = []
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            limit = min(total_pages, max_pages) if max_pages > 0 else total_pages
            for idx in range(limit):
                page = doc.load_page(idx)
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                filename = self.output_dir / f"{doc_filename}-page-{idx + 1}.png"
                pix.save(str(filename))
                fallback_exported.append({
                    "type": "page",
                    "page": idx + 1,
                    "path": str(filename)
                })
            doc.close()
        except Exception as e:
            print(f"❌ Gagal fallback render page: {e}")
        return fallback_exported

    def _render_specific_pages(self, pdf_path: str, doc_filename: str, pages: Iterable[int], dpi: int = 120):
        exported = []
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            for page_no in pages:
                if page_no < 1 or page_no > total_pages:
                    continue
                page = doc.load_page(page_no - 1)
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                filename = self.output_dir / f"{doc_filename}-page-{page_no}.png"
                pix.save(str(filename))
                exported.append({
                    "type": "page",
                    "page": page_no,
                    "path": str(filename)
                })
            doc.close()
        except Exception as e:
            print(f"❌ Gagal render specific pages: {e}")
        return exported
