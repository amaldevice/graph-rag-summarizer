# ============================================================
# MAIN LAUNCHER TESTS
# Summary edit-loop and final dispatch behavior.
# ============================================================

import sys
import importlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def test_main_reopens_wizard_when_summary_requests_edit(monkeypatch):
    launcher_main = importlib.import_module("main")

    class FakeParser:
        def parse_args(self):
            class Args:
                mode = "ingest"
                profile = None
                collection = None
                query = None
                retrieval_limit = None
                pdf = None
                no_interactive = False
                json_output = None
                confirm_existing_collection = False

            return Args()

    class FakeStdin:
        @staticmethod
        def isatty():
            return True

    configs = iter([
        {
            "mode": "ingest",
            "profile": "local",
            "collection": "first_collection",
            "pdf_path": "first.pdf",
            "query": "",
            "retrieval_limit": 10,
            "json_output": "",
            "confirm_existing_collection": False,
        },
        {
            "mode": "ingest",
            "profile": "local",
            "collection": "final_collection",
            "pdf_path": "final.pdf",
            "query": "",
            "retrieval_limit": 10,
            "json_output": "",
            "confirm_existing_collection": False,
        },
    ])

    confirmation = iter([False, True])
    called = {}

    monkeypatch.setattr(launcher_main, "build_cli_parser", lambda: FakeParser())
    monkeypatch.setattr(launcher_main.sys, "stdin", FakeStdin())
    monkeypatch.setattr(launcher_main, "resolve_profile", lambda cli, env: "local")
    monkeypatch.setattr(launcher_main, "resolve_mode", lambda mode: mode)
    monkeypatch.setattr(launcher_main, "run_interactive_wizard", lambda *args, **kwargs: next(configs))
    monkeypatch.setattr(launcher_main, "check_availability", lambda mode, profile: [])
    monkeypatch.setattr(launcher_main, "show_summary_and_confirm", lambda config, is_tty: next(confirmation))
    monkeypatch.setattr(launcher_main, "run_ingest", lambda config: called.update(config))

    launcher_main.main()

    assert called["collection"] == "final_collection"
    assert called["pdf_path"] == "final.pdf"
