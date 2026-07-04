import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import importlib


def test_upload_exported_images_uses_storage_handler_contract(monkeypatch) -> None:
    uploads: list[tuple[str, str]] = []

    docling_module = types.ModuleType("docling")
    document_converter_module = types.ModuleType("docling.document_converter")
    document_converter_module.DocumentConverter = type("DocumentConverter", (), {})
    docling_module.document_converter = document_converter_module

    docling_core_module = types.ModuleType("docling_core")
    docling_core_types_module = types.ModuleType("docling_core.types")
    docling_core_doc_module = types.ModuleType("docling_core.types.doc")
    docling_core_doc_module.PictureItem = type("PictureItem", (), {})
    docling_core_doc_module.TableItem = type("TableItem", (), {})
    docling_core_types_module.doc = docling_core_doc_module
    docling_core_module.types = docling_core_types_module

    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter_module)
    monkeypatch.setitem(sys.modules, "docling_core", docling_core_module)
    monkeypatch.setitem(sys.modules, "docling_core.types", docling_core_types_module)
    monkeypatch.setitem(sys.modules, "docling_core.types.doc", docling_core_doc_module)

    docling_loader = importlib.import_module("preprocessing.docling_loader")
    docling_loader = importlib.reload(docling_loader)

    class FakeStorageHandler:
        def upload_local_path(self, file_path: str, object_name: str | None = None, content_type: str = "image/png") -> str:
            del content_type
            uploads.append((file_path, object_name or ""))
            return object_name or ""

        def build_image_url(self, object_name: str) -> str:
            return f"https://local.example/{object_name}"

    loader = docling_loader.DoclingLoader.__new__(docling_loader.DoclingLoader)
    loader.storage_handler = FakeStorageHandler()

    uploaded = loader._upload_exported_images(
        [{"type": "page", "page": 1, "path": "/tmp/page-1.png"}],
        "paper",
    )

    assert uploads == [("/tmp/page-1.png", "images/paper/page-1.png")]
    assert uploaded == [{
        "type": "page",
        "page": 1,
        "object_name": "images/paper/page-1.png",
        "image_url": "https://local.example/images/paper/page-1.png",
    }]
