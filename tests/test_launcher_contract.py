# ============================================================
# LAUNCHER CONTRACT TESTS
# Mode resolution, precedence rules, non-interactive fail-fast,
# availability checks, collection discovery, and summary.
# ============================================================

import sys
from types import SimpleNamespace
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from launcher.contract import (
    check_availability,
    resolve_mode,
    resolve_profile,
    suggest_collection_from_pdf,
    suggest_document_id_from_pdf,
    discover_collections,
    discover_local_pdfs,
    build_cli_parser,
    _fail_fast_missing,
    _profile_from_backend_selectors,
    run_interactive_wizard,
    show_summary_and_confirm,
    SUPPORTED_MODES,
    SUPPORTED_PROFILES,
    DEFAULT_RETRIEVAL_LIMIT,
    SUPPORTED_INGEST_MODES,
    DEFAULT_INGEST_MODE,
    SUPPORTED_COLLECTION_MODES,
    DEFAULT_COLLECTION_MODE,
    resolve_collection_mode,
)


# ------------------------------------------------------------------
# Profile resolution
# ------------------------------------------------------------------

def test_resolve_profile_returns_cli_profile_when_provided():
    assert resolve_profile("cloud", None) == "cloud"
    assert resolve_profile("local", "cloud") == "local"


def test_resolve_profile_falls_back_to_env():
    assert resolve_profile(None, "cloud") == "cloud"
    assert resolve_profile(None, "local") == "local"


def test_resolve_profile_defaults_to_local(monkeypatch):
    monkeypatch.delenv("QDRANT_BACKEND", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert resolve_profile(None, None) == "local"


def test_resolve_profile_rejects_unknown_cli():
    with pytest.raises(ValueError, match="Unknown profile 'bad'"):
        resolve_profile("bad", None)


def test_resolve_profile_rejects_unknown_env():
    with pytest.raises(ValueError, match="Unknown profile 'bad'"):
        resolve_profile(None, "bad")


def test_profile_from_backend_selectors_cloud(monkeypatch):
    monkeypatch.setenv("QDRANT_BACKEND", "cloud")
    assert _profile_from_backend_selectors() == "cloud"


def test_profile_from_backend_selectors_auto_with_url(monkeypatch):
    monkeypatch.setenv("QDRANT_BACKEND", "auto")
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    assert _profile_from_backend_selectors() == "cloud"


def test_profile_from_backend_selectors_auto_without_url(monkeypatch):
    monkeypatch.setenv("QDRANT_BACKEND", "auto")
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert _profile_from_backend_selectors() == "local"


# ------------------------------------------------------------------
# Mode resolution
# ------------------------------------------------------------------

def test_resolve_mode_returns_mode_when_provided():
    for mode in SUPPORTED_MODES:
        assert resolve_mode(mode) == mode


def test_resolve_mode_normalizes_case():
    assert resolve_mode("Query-Only") == "query-only"
    assert resolve_mode("INGEST") == "ingest"


def test_resolve_mode_returns_none_when_not_provided():
    assert resolve_mode(None) is None


def test_resolve_mode_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown mode 'bad'"):
        resolve_mode("bad")


# ------------------------------------------------------------------
# Availability checks
# ------------------------------------------------------------------

def test_ingest_always_available():
    assert check_availability("ingest", "local") == []
    assert check_availability("ingest", "cloud") == []


def test_query_only_local_needs_no_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert check_availability("query-only", "local") == []


def test_query_only_cloud_requires_qdrant_url(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    missing = check_availability("query-only", "cloud")
    assert any("QDRANT_URL" in m for m in missing)


def test_query_only_cloud_requires_qdrant_api_key(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    missing = check_availability("query-only", "cloud")
    assert any("QDRANT_API_KEY" in m for m in missing)


def test_query_only_does_not_require_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert check_availability("query-only", "local") == []


def test_full_pipeline_requires_at_least_one_llm_provider(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    missing = check_availability("full-pipeline", "local")
    assert any("At least one configured LLM provider" in m for m in missing)


def test_full_pipeline_cloud_requires_qdrant_and_any_llm_provider(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    missing = check_availability("full-pipeline", "cloud")
    assert len(missing) >= 2


# ------------------------------------------------------------------
# Collection discovery
# ------------------------------------------------------------------

def test_discover_collections_returns_empty_on_failure(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "vectordb.qdrant_handler":
            raise ConnectionError("no qdrant")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    assert discover_collections("local") == []


def test_suggest_collection_from_pdf():
    assert suggest_collection_from_pdf("/path/to/My Paper.pdf") == "my_paper"
    assert suggest_collection_from_pdf("report-2024.pdf") == "report-2024"
    assert suggest_collection_from_pdf("my file name.pdf") == "my_file_name"


def test_suggest_document_id_from_pdf_uses_safe_filename_stem():
    assert suggest_document_id_from_pdf("/path/to/My Paper.pdf") == "my_paper"


def test_supported_ingest_modes_have_append_default():
    assert SUPPORTED_INGEST_MODES == ("append", "replace-document", "replace-collection")
    assert DEFAULT_INGEST_MODE == "append"


def test_collection_mode_defaults_to_document_safe_and_rejects_unknown_values():
    assert SUPPORTED_COLLECTION_MODES == ("document-safe", "legacy-vector")
    assert DEFAULT_COLLECTION_MODE == "document-safe"
    assert resolve_collection_mode(None) == "document-safe"
    assert resolve_collection_mode("LEGACY-VECTOR") == "legacy-vector"
    with pytest.raises(ValueError, match="Unknown collection mode 'unknown'"):
        resolve_collection_mode("unknown")


def test_discover_local_pdfs_returns_repo_relative_sorted_paths(tmp_path):
    (tmp_path / "alpha.pdf").write_text("a")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "beta.PDF").write_text("b")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "skip.pdf").write_text("skip")

    result = discover_local_pdfs(tmp_path)

    assert result == ["alpha.pdf", "docs/beta.PDF"]


# ------------------------------------------------------------------
# CLI parsing
# ------------------------------------------------------------------

def test_build_cli_parser_has_all_flags():
    parser = build_cli_parser()
    args = parser.parse_args([
        "--mode", "query-only",
        "--profile", "local",
        "--collection", "test_col",
        "--query", "what is X",
        "--retrieval-limit", "5",
        "--pdf", "test.pdf",
        "--no-interactive",
        "--json-output", "out.json",
        "--artifact-dir", "artifacts/run-1",
        "--verbose",
        "--collection-mode", "legacy-vector",
        "--ingest-mode", "append",
        "--document-id", "paper-a",
    ])
    assert args.mode == "query-only"
    assert args.profile == "local"
    assert args.collection == "test_col"
    assert args.query == "what is X"
    assert args.retrieval_limit == 5
    assert args.pdf == "test.pdf"
    assert args.no_interactive is True
    assert args.json_output == "out.json"
    assert args.artifact_dir == "artifacts/run-1"
    assert args.verbose is True
    assert args.collection_mode == "legacy-vector"
    assert args.ingest_mode == "append"
    assert args.document_id == "paper-a"


def test_build_cli_parser_defaults():
    parser = build_cli_parser()
    args = parser.parse_args([])
    assert args.mode is None
    assert args.profile is None
    assert args.collection is None
    assert args.query is None
    assert args.retrieval_limit is None
    assert args.pdf is None
    assert args.no_interactive is False
    assert args.json_output is None
    assert args.artifact_dir is None
    assert args.verbose is False
    assert args.collection_mode is None
    assert args.ingest_mode is None
    assert args.document_id is None


def test_cli_rejects_test_only_feedback_retry_override():
    with pytest.raises(SystemExit):
        build_cli_parser().parse_args(["--test-force-feedback-retry-stage", "prompt"])


# ------------------------------------------------------------------
# Non-interactive fail-fast
# ------------------------------------------------------------------

def _make_args(**kwargs):
    defaults = {
        "mode": None,
        "profile": "local",
        "collection": None,
        "query": None,
        "retrieval_limit": None,
        "pdf": None,
        "no_interactive": True,
        "json_output": None,
        "artifact_dir": None,
        "verbose": False,
        "confirm_existing_collection": False,
        "collection_mode": None,
    }
    defaults.update(kwargs)

    class Args:
        pass

    a = Args()
    for k, v in defaults.items():
        setattr(a, k, v)
    return a


def test_fail_fast_requires_mode():
    args = _make_args(mode=None)
    with pytest.raises(SystemExit, match="--mode is required"):
        _fail_fast_missing(args, "local")


def test_fail_fast_requires_collection_for_query_only():
    args = _make_args(mode="query-only", collection=None, query="test")
    with pytest.raises(SystemExit, match="--collection is required"):
        _fail_fast_missing(args, "local")


def test_fail_fast_requires_query_for_query_only():
    args = _make_args(mode="query-only", collection="col", query=None)
    with pytest.raises(SystemExit, match="--query is required"):
        _fail_fast_missing(args, "local")


def test_fail_fast_requires_pdf_for_ingest():
    args = _make_args(mode="ingest", pdf=None)
    with pytest.raises(SystemExit, match="--pdf is required"):
        _fail_fast_missing(args, "local")


def test_fail_fast_suggests_collection_from_pdf():
    args = _make_args(mode="ingest", pdf="my_paper.pdf", collection=None)
    result = _fail_fast_missing(args, "local")
    assert result["collection"] == "my_paper"


def test_fail_fast_suggests_document_id_and_append_mode_for_ingest():
    args = _make_args(mode="ingest", pdf="my_paper.pdf", collection=None)
    result = _fail_fast_missing(args, "local")
    assert result["document_id"] == "my_paper"
    assert result["ingest_mode"] == "append"


def test_fail_fast_allows_existing_collection_for_safe_append(monkeypatch):
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: ["my_paper"])
    args = _make_args(mode="ingest", pdf="my_paper.pdf", collection="my_paper")
    result = _fail_fast_missing(args, "local")
    assert result["collection"] == "my_paper"
    assert result["ingest_mode"] == "append"


def test_fail_fast_allows_existing_ingest_collection_with_confirmation(monkeypatch):
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: ["my_paper"])
    args = _make_args(
        mode="ingest",
        pdf="my_paper.pdf",
        collection="my_paper",
        confirm_existing_collection=True,
    )
    result = _fail_fast_missing(args, "local")
    assert result["collection"] == "my_paper"
    assert result["confirm_existing_collection"] is True


def test_fail_fast_preserves_explicit_replace_ingest_mode(monkeypatch):
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: ["my_paper"])
    args = _make_args(
        mode="ingest",
        pdf="my_paper.pdf",
        collection="my_paper",
        ingest_mode="replace-document",
        document_id="paper-a",
    )
    result = _fail_fast_missing(args, "local")
    assert result["ingest_mode"] == "replace-document"
    assert result["document_id"] == "paper-a"


def test_fail_fast_query_only_success():
    args = _make_args(mode="query-only", collection="col", query="test q")
    result = _fail_fast_missing(args, "local")
    assert result["mode"] == "query-only"
    assert result["collection"] == "col"
    assert result["query"] == "test q"
    assert result["retrieval_limit"] == DEFAULT_RETRIEVAL_LIMIT
    assert result["collection_mode"] == "document-safe"


def test_fail_fast_full_pipeline_requires_query():
    args = _make_args(mode="full-pipeline", collection="col", query=None)
    with pytest.raises(SystemExit, match="--query is required"):
        _fail_fast_missing(args, "local")


def test_fail_fast_json_output_defaults():
    args = _make_args(mode="query-only", collection="col", query="q", json_output=None)
    result = _fail_fast_missing(args, "local")
    assert result["json_output"] == "output/query_only_results.json"


def test_fail_fast_full_pipeline_artifact_dir_defaults():
    args = _make_args(mode="full-pipeline", collection="col", query="q", artifact_dir=None)
    result = _fail_fast_missing(args, "local")
    assert re.match(
        r"^output/full_pipeline_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$",
        result["artifact_dir"],
    )


def test_run_interactive_wizard_uses_discovered_pdf_then_default_collection(monkeypatch, tmp_path):
    (tmp_path / "paper one.pdf").write_text("x")
    (tmp_path / "notes.txt").write_text("nope")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: [])

    answers = iter(["1", "", "", "", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection=None,
        query=None,
        retrieval_limit=None,
        pdf=None,
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["pdf_path"] == "paper one.pdf"
    assert result["collection"] == "paper_one"
    assert result["document_id"] == "paper_one"


def test_run_interactive_wizard_prompts_for_ingest_mode_when_cli_omits_it(monkeypatch):
    answers = iter(["2", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection="existing_collection",
        query=None,
        retrieval_limit=None,
        pdf="paper.pdf",
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode=None,
        document_id=None,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["ingest_mode"] == "replace-document"


def test_run_interactive_wizard_accepts_a_custom_document_id(monkeypatch):
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return "paper-recovery"

    monkeypatch.setattr("builtins.input", fake_input)
    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection="existing_collection",
        query=None,
        retrieval_limit=None,
        pdf="paper.pdf",
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode="append",
        document_id=None,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["document_id"] == "paper-recovery"
    assert any("Document ID" in prompt for prompt in prompts)


def test_run_interactive_wizard_keeps_explicit_document_id_locked(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("unexpected prompt"))
    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection="existing_collection",
        query=None,
        retrieval_limit=None,
        pdf="paper.pdf",
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode="append",
        document_id="paper-cli",
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["document_id"] == "paper-cli"


def test_edit_defaults_reopen_ingest_mode_and_document_id(monkeypatch):
    from main import _config_to_args

    config = {
        "mode": "ingest",
        "profile": "local",
        "collection": "first_collection",
        "collection_mode": "document-safe",
        "pdf_path": "first.pdf",
        "ingest_mode": "append",
        "document_id": "first_document",
        "query": "",
        "retrieval_limit": 10,
        "json_output": "",
        "artifact_dir": "",
        "verbose": False,
        "confirm_existing_collection": False,
        "collection_operation_id": "",
        "enable_graph_artifact": True,
    }
    original_args = SimpleNamespace(
        profile=None,
        collection=None,
        collection_mode=None,
        query=None,
        retrieval_limit=None,
        pdf=None,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
        ingest_mode=None,
        document_id=None,
        collection_operation_id=None,
    )
    monkeypatch.setattr("launcher.contract.discover_local_pdfs", lambda *_: [])
    answers = iter(["", "", "", "", "2", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = run_interactive_wizard(
        _config_to_args(config, original_args),
        "local",
        is_tty=True,
    )

    assert result["collection"] == "first_collection"
    assert result["pdf_path"] == "first.pdf"
    assert result["ingest_mode"] == "replace-document"
    assert result["document_id"] == "first_document"


def test_edit_defaults_reopen_query_only_fields(monkeypatch):
    from main import _config_to_args

    config = {
        "mode": "query-only",
        "profile": "local",
        "collection": "first_collection",
        "collection_mode": "document-safe",
        "query": "first query",
        "retrieval_limit": 10,
        "pdf_path": "",
        "json_output": "output/first.json",
        "artifact_dir": "",
        "verbose": False,
        "confirm_existing_collection": False,
        "ingest_mode": "append",
        "document_id": "",
        "collection_operation_id": "",
        "enable_graph_artifact": True,
    }
    original_args = SimpleNamespace(
        profile=None,
        collection=None,
        collection_mode=None,
        query=None,
        retrieval_limit=None,
        pdf=None,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
        ingest_mode=None,
        document_id=None,
        collection_operation_id=None,
    )
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: [])
    answers = iter(["", "", "", "edited query", "12", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    result = run_interactive_wizard(
        _config_to_args(config, original_args),
        "local",
        is_tty=True,
    )

    assert result["collection"] == "first_collection"
    assert result["query"] == "edited query"
    assert result["retrieval_limit"] == 12
    assert result["json_output"] == "output/first.json"


def test_edit_defaults_preserve_explicit_cli_fields():
    from main import _config_to_args

    config = {
        "mode": "ingest",
        "profile": "cloud",
        "collection": "interactive_collection",
        "collection_mode": "document-safe",
        "pdf_path": "interactive.pdf",
        "ingest_mode": "replace-document",
        "document_id": "interactive_document",
        "query": "",
        "retrieval_limit": 10,
        "json_output": "",
        "artifact_dir": "",
        "verbose": False,
        "confirm_existing_collection": False,
        "collection_operation_id": "",
        "enable_graph_artifact": True,
    }
    original_args = SimpleNamespace(
        profile="local",
        collection="cli_collection",
        collection_mode="legacy-vector",
        query=None,
        retrieval_limit=None,
        pdf="cli.pdf",
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode="append",
        document_id="cli_document",
        collection_operation_id=None,
    )

    edit_args = _config_to_args(config, original_args)

    assert edit_args.profile == "local"
    assert edit_args.collection == "cli_collection"
    assert edit_args.collection_mode == "legacy-vector"
    assert edit_args.pdf == "cli.pdf"
    assert edit_args.ingest_mode == "append"
    assert edit_args.document_id == "cli_document"
    assert edit_args.verbose is True


def test_run_interactive_wizard_selects_collection_design_after_launcher_mode(monkeypatch):
    answers = iter(["2", "2", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    args = SimpleNamespace(
        mode=None,
        profile="local",
        collection="existing_collection",
        query=None,
        retrieval_limit=None,
        pdf="paper.pdf",
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode="append",
        document_id=None,
        collection_mode=None,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["mode"] == "ingest"
    assert result["collection_mode"] == "legacy-vector"
    assert result["enable_graph_artifact"] is False


def test_run_interactive_wizard_preserves_explicit_ingest_mode(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection="existing_collection",
        query=None,
        retrieval_limit=None,
        pdf="paper.pdf",
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
        ingest_mode="replace-document",
        document_id=None,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["ingest_mode"] == "replace-document"


def test_run_interactive_wizard_allows_existing_collection_for_append(monkeypatch, capsys):
    monkeypatch.setattr("launcher.contract.discover_local_pdfs", lambda *_: [])
    monkeypatch.setattr("launcher.contract.discover_collections", lambda profile: ["existing_collection"])

    answers = iter([
        "paper.pdf",
        "existing_collection",
        "",
        "",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    args = SimpleNamespace(
        mode="ingest",
        profile="local",
        collection=None,
        query=None,
        retrieval_limit=None,
        pdf=None,
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["collection"] == "existing_collection"
    output = capsys.readouterr().out
    assert "Existing collections detected" in output
    assert "already exists" not in output


def test_run_interactive_wizard_prompts_for_profile_when_not_locked(monkeypatch):
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    args = SimpleNamespace(
        mode="query-only",
        profile=None,
        collection="col",
        query="q",
        retrieval_limit=1,
        pdf=None,
        no_interactive=False,
        json_output="out.json",
        artifact_dir=None,
        verbose=True,
        confirm_existing_collection=False,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["profile"] == "cloud"


def test_run_interactive_wizard_uses_json_output_label_for_query_only(monkeypatch):
    prompts = []
    answers = iter(["output/query.json", "n"])

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    args = SimpleNamespace(
        mode="query-only",
        profile="local",
        collection="col",
        query="q",
        retrieval_limit=1,
        pdf=None,
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["json_output"] == "output/query.json"
    assert any("JSON output path" in prompt for prompt in prompts)


def test_run_interactive_wizard_uses_artifact_dir_label_for_full_pipeline(monkeypatch):
    prompts = []
    answers = iter(["output/run-1", "", "n"])

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    args = SimpleNamespace(
        mode="full-pipeline",
        profile="local",
        collection="col",
        query="q",
        retrieval_limit=1,
        pdf=None,
        no_interactive=False,
        json_output=None,
        artifact_dir=None,
        verbose=False,
        confirm_existing_collection=False,
    )

    result = run_interactive_wizard(args, "local", is_tty=True)

    assert result["artifact_dir"] == "output/run-1"
    assert any("Artifact output directory" in prompt for prompt in prompts)
    assert not any("JSON output path" in prompt for prompt in prompts)


def test_show_summary_and_confirm_uses_no_as_edit(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    result = show_summary_and_confirm(
        {
            "mode": "ingest",
            "profile": "local",
            "collection": "paper",
            "pdf_path": "paper.pdf",
        },
        is_tty=True,
    )

    assert result is False


def test_show_summary_and_confirm_displays_artifact_dir_for_full_pipeline(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    result = show_summary_and_confirm(
        {
            "mode": "full-pipeline",
            "profile": "cloud",
            "collection": "paper",
            "query": "q",
            "retrieval_limit": 5,
            "artifact_dir": "output/run-1",
            "verbose": True,
        },
        is_tty=True,
    )

    assert result is True
    output = capsys.readouterr().out
    assert "Artifact Dir" in output
    assert "output/run-1" in output
