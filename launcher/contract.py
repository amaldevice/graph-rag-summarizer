# ============================================================
# LAUNCHER CONTRACT
# Profile resolution, mode resolution, availability checks,
# collection discovery, CLI parsing, and interactive wizard.
# ============================================================

import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_MODES = ("query-only", "ingest", "full-pipeline")
SUPPORTED_PROFILES = ("local", "cloud")
SUPPORTED_LLM_PROVIDERS = ("groq", "gemini", "nvidia", "openrouter")
SUPPORTED_INGEST_MODES = ("append", "replace-document", "replace-collection")
SUPPORTED_COLLECTION_MODES = ("document-safe", "legacy-vector")
DEFAULT_RETRIEVAL_LIMIT = 10
DEFAULT_INGEST_MODE = "append"
DEFAULT_COLLECTION_MODE = "document-safe"
EXCLUDED_SCAN_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".commandcode",
    ".omx",
}


def _persistent_graph_enabled() -> bool:
    from config import settings

    return bool(settings.ENABLE_PERSISTENT_GRAPH)


def build_chunk_uid(document_id: str, chunk_id) -> str:
    return f"{document_id}:chunk:{chunk_id}"


def build_stable_point_id(document_id: str, chunk_id) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"graph-rag:{build_chunk_uid(document_id, chunk_id)}"))


# ------------------------------------------------------------------
# Profile resolution
# ------------------------------------------------------------------

def resolve_profile(cli_profile: str | None, env_profile: str | None) -> str:
    """Resolve Launch Profile with precedence: CLI > env > local default."""
    if cli_profile:
        profile = cli_profile.lower().strip()
        if profile not in SUPPORTED_PROFILES:
            raise ValueError(
                f"Unknown profile '{profile}'. Choose from: {', '.join(SUPPORTED_PROFILES)}"
            )
        return profile
    if env_profile:
        profile = env_profile.lower().strip()
        if profile not in SUPPORTED_PROFILES:
            raise ValueError(
                f"Unknown profile '{profile}' in LAUNCHER_PROFILE. Choose from: {', '.join(SUPPORTED_PROFILES)}"
            )
        return profile
    return _profile_from_backend_selectors()


def _profile_from_backend_selectors() -> str:
    """Derive profile from legacy backend selectors for backward compatibility."""
    qdrant_backend = os.getenv("QDRANT_BACKEND", "auto").lower().strip()
    qdrant_url = os.getenv("QDRANT_URL", "").strip()

    if qdrant_backend == "cloud" or (qdrant_backend == "auto" and qdrant_url):
        return "cloud"
    return "local"


# ------------------------------------------------------------------
# Mode resolution
# ------------------------------------------------------------------

def resolve_mode(cli_mode: str | None) -> str | None:
    """Resolve Launcher Mode from CLI. Returns None if not provided."""
    if cli_mode is None:
        return None
    mode = cli_mode.lower().strip()
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unknown mode '{mode}'. Choose from: {', '.join(SUPPORTED_MODES)}"
        )
    return mode


def resolve_ingest_mode(ingest_mode: str | None) -> str:
    """Resolve the explicit collection lifecycle operation for an ingest run."""
    mode = (ingest_mode or DEFAULT_INGEST_MODE).lower().strip()
    if mode not in SUPPORTED_INGEST_MODES:
        raise ValueError(
            f"Unknown ingest mode '{mode}'. Choose from: {', '.join(SUPPORTED_INGEST_MODES)}"
        )
    return mode


def resolve_collection_mode(collection_mode: str | None) -> str:
    """Resolve the collection design selected for a launcher run."""
    mode = (collection_mode or DEFAULT_COLLECTION_MODE).lower().strip()
    if mode not in SUPPORTED_COLLECTION_MODES:
        raise ValueError(
            f"Unknown collection mode '{mode}'. Choose from: {', '.join(SUPPORTED_COLLECTION_MODES)}"
        )
    return mode


# ------------------------------------------------------------------
# Availability checks
# ------------------------------------------------------------------

def check_availability(mode: str, profile: str) -> list[str]:
    """Return a list of missing configuration items for the given mode+profile.

    An empty list means the mode is available.
    """
    missing = []

    if mode == "ingest":
        return missing

    if mode in ("query-only", "full-pipeline"):
        if profile == "cloud":
            if not os.getenv("QDRANT_URL", "").strip():
                missing.append("QDRANT_URL is required for cloud profile")
            if not os.getenv("QDRANT_API_KEY", "").strip():
                missing.append("QDRANT_API_KEY is required for cloud profile")
        elif profile == "local":
            pass

    if mode == "full-pipeline":
        if not _has_available_llm_provider():
            missing.append(_full_pipeline_llm_error())

    return missing


def _has_available_llm_provider() -> bool:
    preferred_provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    enable_fallback = os.getenv("LLM_ENABLE_FALLBACK", "True").strip().lower() == "true"
    fallback_chain = [
        provider.strip().lower()
        for provider in os.getenv("LLM_FALLBACK_CHAIN", "groq,gemini,nvidia,openrouter").split(",")
        if provider.strip()
    ]

    if not enable_fallback:
        return not _missing_llm_fields(preferred_provider)

    providers_to_check = []
    for provider in [preferred_provider, *fallback_chain]:
        if provider in SUPPORTED_LLM_PROVIDERS and provider not in providers_to_check:
            providers_to_check.append(provider)

    return any(not _missing_llm_fields(provider) for provider in providers_to_check)


def _missing_llm_fields(provider: str) -> list[str]:
    requirements = {
        "groq": (
            ("GROQ_API_KEY", os.getenv("GROQ_API_KEY", "")),
            ("GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")),
        ),
        "gemini": (
            ("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", "")),
            ("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash")),
        ),
        "nvidia": (
            ("NVIDIA_NIM_API_KEY", os.getenv("NVIDIA_NIM_API_KEY", "")),
            ("NVIDIA_NIM_MODEL", os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")),
            ("NVIDIA_NIM_BASE_URL", os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")),
        ),
        "openrouter": (
            ("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
            ("OPENROUTER_MODEL", os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct")),
            ("OPENROUTER_BASE_URL", os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")),
        ),
    }
    fields = requirements.get(provider)
    if not fields:
        return [f"unknown provider '{provider}'"]
    return [field for field, value in fields if not value.strip()]


def _full_pipeline_llm_error() -> str:
    preferred_provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    enable_fallback = os.getenv("LLM_ENABLE_FALLBACK", "True").strip().lower() == "true"

    if not enable_fallback:
        missing_fields = _missing_llm_fields(preferred_provider)
        return (
            f"{preferred_provider} is required for Full-Pipeline Run when fallback is disabled: "
            f"missing {', '.join(missing_fields)}"
        )

    return (
        "At least one configured LLM provider is required for Full-Pipeline Run "
        "(Groq, Gemini, NVIDIA NIM, or OpenRouter)."
    )


# ------------------------------------------------------------------
# Collection discovery
# ------------------------------------------------------------------

def discover_collections(profile: str) -> list[str]:
    """Try to list collection names from Qdrant. Returns [] on failure."""
    try:
        from vectordb.qdrant_handler import QdrantHandler
        handler = QdrantHandler(
            qdrant_backend="cloud" if profile == "cloud" else "local",
            qdrant_url=os.getenv("QDRANT_URL", "").strip(),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        )
        collections = handler.client.get_collections().collections
        return [c.name for c in collections]
    except Exception:
        return []


def suggest_collection_from_pdf(pdf_path: str) -> str:
    """Derive a safe Collection Target name from a PDF filename."""
    stem = Path(pdf_path).stem
    safe = "".join(c if c.isalnum() or c == "-" else "_" for c in stem)
    return safe.lower().strip("_")


def suggest_document_id_from_pdf(pdf_path: str) -> str:
    """Derive a stable, human-readable document ID from a PDF filename."""
    return suggest_collection_from_pdf(pdf_path)


def discover_local_pdfs(search_root: str | Path = ".") -> list[str]:
    """Discover repo-local PDFs for common ingest usage."""
    root = Path(search_root)
    if not root.exists():
        return []

    found: list[str] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_SCAN_DIRS and not d.startswith(".")]
        current_path = Path(current_root)
        for name in files:
            if Path(name).suffix.lower() != ".pdf":
                continue
            full_path = current_path / name
            found.append(full_path.relative_to(root).as_posix())
    return sorted(found)


def default_full_pipeline_artifact_dir() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    return f"output/full_pipeline_{timestamp}"


# ------------------------------------------------------------------
# CLI argument parsing
# ------------------------------------------------------------------

def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main",
        description="Graph RAG Summarizer — single launcher",
    )
    parser.add_argument(
        "--mode",
        choices=SUPPORTED_MODES,
        help="Launcher mode: query-only, ingest, or full-pipeline",
    )
    parser.add_argument(
        "--profile",
        choices=SUPPORTED_PROFILES,
        help="Launch profile: local or cloud",
    )
    parser.add_argument(
        "--collection",
        help="Collection Target name",
    )
    parser.add_argument(
        "--collection-mode",
        choices=SUPPORTED_COLLECTION_MODES,
        default=None,
        help="Collection design: document-safe or legacy-vector (default: document-safe)",
    )
    parser.add_argument(
        "--query",
        help="Query text (required for query-only and full-pipeline)",
    )
    parser.add_argument(
        "--retrieval-limit",
        type=int,
        default=None,
        help=f"Number of chunks to retrieve (default: {DEFAULT_RETRIEVAL_LIMIT})",
    )
    parser.add_argument(
        "--pdf",
        help="Local PDF path for ingest or optional page-image enrichment",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        default=False,
        help="Disable interactive prompts; fail fast on missing inputs",
    )
    parser.add_argument(
        "--json-output",
        help="Path to write the Query-Only Run JSON artifact",
    )
    parser.add_argument(
        "--artifact-dir",
        help="Directory to write Full-Pipeline Run artifacts",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable clearer stage-level diagnostic logging",
    )
    parser.add_argument(
        "--confirm-existing-collection",
        action="store_true",
        default=False,
        help="Legacy compatibility flag; explicit --ingest-mode controls the collection operation",
    )
    parser.add_argument(
        "--ingest-mode",
        choices=SUPPORTED_INGEST_MODES,
        default=None,
        help="Collection operation for ingest: append, replace-document, or replace-collection (default: append)",
    )
    parser.add_argument(
        "--document-id",
        help="Stable document identifier for shared-collection ingest (defaults to the PDF filename)",
    )
    parser.add_argument(
        "--collection-operation-id",
        help="Persisted replace-collection operation id used only to resume an interrupted collection claim",
    )
    return parser


# ------------------------------------------------------------------
# Interactive wizard
# ------------------------------------------------------------------

def _prompt_choice(prompt_text: str, options: list[str], default: str | None = None) -> str:
    """Prompt user to pick from numbered options."""
    print(f"\n{prompt_text}")
    for i, opt in enumerate(options, 1):
        suffix = " (default)" if opt == default else ""
        print(f"  {i}. {opt}{suffix}")
    while True:
        raw = input("Choice: ").strip()
        if not raw and default:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            if raw in options:
                return raw
        print(f"Please enter 1-{len(options)} or one of: {', '.join(options)}")


def _prompt_text(prompt_text: str, default: str | None = None, required: bool = False) -> str:
    """Prompt for free-text input."""
    suffix = f" [{default}]" if default else ""
    req = " (required)" if required else ""
    while True:
        raw = input(f"{prompt_text}{suffix}{req}: ").strip()
        if not raw and default:
            return default
        if raw:
            return raw
        if required:
            print("This input is required.")
            continue
        return ""


def run_interactive_wizard(cli_args: argparse.Namespace, profile: str, is_tty: bool) -> dict:
    """Interactive wizard that fills in missing runtime inputs.

    Returns a dict with: mode, profile, collection, query, retrieval_limit, pdf_path, json_output, artifact_dir, verbose.
    """
    if not is_tty:
        return _fail_fast_missing(cli_args, profile)

    if not getattr(cli_args, "profile", None):
        profile = _prompt_choice(
            "Select Launch Profile:",
            list(SUPPORTED_PROFILES),
            default=profile,
        )
    else:
        profile = str(cli_args.profile).lower().strip()

    mode = cli_args.mode
    if not mode:
        mode = _prompt_choice("Select Launcher Mode:", list(SUPPORTED_MODES))

    if hasattr(cli_args, "collection_mode"):
        collection_mode = getattr(cli_args, "collection_mode")
        if collection_mode is None:
            collection_mode = _prompt_choice(
                "Select Collection Design:",
                list(SUPPORTED_COLLECTION_MODES),
                default=DEFAULT_COLLECTION_MODE,
            )
        collection_mode = resolve_collection_mode(collection_mode)
    else:
        # Programmatic callers from the pre-mode launcher contract retain the
        # documented default without an unexpected prompt.
        collection_mode = DEFAULT_COLLECTION_MODE

    collection = cli_args.collection
    query = cli_args.query
    retrieval_limit = cli_args.retrieval_limit
    pdf_path = cli_args.pdf
    json_output = cli_args.json_output
    artifact_dir = getattr(cli_args, "artifact_dir", None)
    verbose = bool(getattr(cli_args, "verbose", False))
    confirm_existing_collection = bool(getattr(cli_args, "confirm_existing_collection", False))
    ingest_mode = resolve_ingest_mode(getattr(cli_args, "ingest_mode", None))
    document_id = getattr(cli_args, "document_id", None)

    if mode in ("query-only", "full-pipeline"):
        if not collection:
            collections = discover_collections(profile)
            if collections:
                collection = _prompt_choice("Select Collection Target:", collections)
            else:
                collection = _prompt_text("Collection Target name", required=True)

        if not query:
            query = _prompt_text("Query text", required=True)

        if retrieval_limit is None:
            raw = _prompt_text(
                "Retrieval limit",
                default=str(DEFAULT_RETRIEVAL_LIMIT),
            )
            try:
                retrieval_limit = int(raw)
            except ValueError:
                retrieval_limit = DEFAULT_RETRIEVAL_LIMIT

    if mode == "ingest":
        if not pdf_path:
            pdf_choices = discover_local_pdfs(Path.cwd())
            if pdf_choices:
                pdf_choice = _prompt_choice(
                    "Select PDF source:",
                    pdf_choices + ["Enter path manually"],
                )
                if pdf_choice == "Enter path manually":
                    pdf_path = _prompt_text("PDF file path", required=True)
                else:
                    pdf_path = pdf_choice
            else:
                pdf_path = _prompt_text("PDF file path", required=True)

        existing_collections = discover_collections(profile)
        if existing_collections:
            print("\nExisting collections detected:")
            for name in existing_collections:
                print(f"  - {name}")

        if not collection:
            suggested = suggest_collection_from_pdf(pdf_path) if pdf_path else ""
        else:
            suggested = collection

        while True:
            if not collection:
                collection = _prompt_text(
                    "Collection Target",
                    default=suggested,
                    required=True,
                )
            break

        if not getattr(cli_args, "ingest_mode", None):
            ingest_mode = _prompt_choice(
                "Select Ingest Mode:",
                list(SUPPORTED_INGEST_MODES),
                default=ingest_mode,
            )

        document_id = document_id or suggest_document_id_from_pdf(pdf_path)

    if mode == "query-only" and not json_output:
        json_output = _prompt_text(
            "JSON output path",
            default="output/query_only_results.json",
        )

    if mode == "full-pipeline" and not artifact_dir:
        artifact_dir = _prompt_text(
            "Artifact output directory",
            default=default_full_pipeline_artifact_dir(),
        )

    if mode == "full-pipeline" and not pdf_path:
        pdf_path = _prompt_text("Optional PDF path for page-image enrichment (leave empty to skip)")

    if not verbose:
        verbose = input("Enable verbose logging? [y/N]: ").strip().lower() in ("y", "yes")

    return {
        "mode": mode,
        "profile": profile,
        "collection": collection or "",
        "query": query or "",
        "retrieval_limit": retrieval_limit or DEFAULT_RETRIEVAL_LIMIT,
        "pdf_path": pdf_path or "",
        "json_output": json_output or "",
        "artifact_dir": artifact_dir or "",
        "verbose": verbose,
        "confirm_existing_collection": confirm_existing_collection,
        "ingest_mode": ingest_mode,
        "document_id": document_id or "",
        "collection_operation_id": getattr(cli_args, "collection_operation_id", "") or "",
        "collection_mode": collection_mode,
        "enable_graph_artifact": (
            collection_mode == "document-safe" and _persistent_graph_enabled()
        ),
    }


def _fail_fast_missing(cli_args: argparse.Namespace, profile: str) -> dict:
    """Build run config from CLI args only; raise if required inputs are missing."""
    mode = cli_args.mode
    if not mode:
        raise SystemExit("Error: --mode is required in non-interactive mode. Use --mode query-only|ingest|full-pipeline")

    collection = cli_args.collection or ""
    query = cli_args.query or ""
    retrieval_limit = cli_args.retrieval_limit or DEFAULT_RETRIEVAL_LIMIT
    pdf_path = cli_args.pdf or ""
    json_output = cli_args.json_output or ""
    artifact_dir = getattr(cli_args, "artifact_dir", None) or ""
    verbose = bool(getattr(cli_args, "verbose", False))
    confirm_existing_collection = bool(getattr(cli_args, "confirm_existing_collection", False))
    ingest_mode = resolve_ingest_mode(getattr(cli_args, "ingest_mode", None))
    document_id = getattr(cli_args, "document_id", None)
    collection_operation_id = getattr(cli_args, "collection_operation_id", None)
    collection_mode = resolve_collection_mode(getattr(cli_args, "collection_mode", None))

    if mode in ("query-only", "full-pipeline"):
        if not collection:
            raise SystemExit("Error: --collection is required for non-interactive mode")
        if not query:
            raise SystemExit("Error: --query is required for non-interactive mode")

    if mode == "ingest":
        if not pdf_path:
            raise SystemExit("Error: --pdf is required for non-interactive ingest mode")
        if not collection:
            collection = suggest_collection_from_pdf(pdf_path)
        document_id = document_id or suggest_document_id_from_pdf(pdf_path)

    if mode == "query-only" and not json_output:
        json_output = f"output/{mode.replace('-', '_')}_results.json"
    if mode == "full-pipeline" and not artifact_dir:
        artifact_dir = default_full_pipeline_artifact_dir()

    return {
        "mode": mode,
        "profile": profile,
        "collection": collection,
        "query": query,
        "retrieval_limit": retrieval_limit,
        "pdf_path": pdf_path,
        "json_output": json_output,
        "artifact_dir": artifact_dir,
        "verbose": verbose,
        "confirm_existing_collection": confirm_existing_collection,
        "ingest_mode": ingest_mode,
        "document_id": document_id or "",
        "collection_operation_id": collection_operation_id or "",
        "collection_mode": collection_mode,
        "enable_graph_artifact": (
            collection_mode == "document-safe" and _persistent_graph_enabled()
        ),
    }


# ------------------------------------------------------------------
# Summary confirmation
# ------------------------------------------------------------------

def show_summary_and_confirm(config: dict, is_tty: bool) -> bool:
    """Show run summary and ask for confirmation. Returns True if user confirms."""
    print("\n--- Run Summary ---")
    print(f"  Mode      : {config['mode']}")
    print(f"  Profile   : {config['profile']}")
    print(f"  Collection: {config['collection']}")
    print(f"  Collection Design: {config.get('collection_mode', DEFAULT_COLLECTION_MODE)}")
    if config.get("query"):
        print(f"  Query     : {config['query']}")
    if config.get("retrieval_limit"):
        print(f"  Limit     : {config['retrieval_limit']}")
    if config.get("pdf_path"):
        print(f"  PDF       : {config['pdf_path']}")
    if config["mode"] == "ingest":
        print(f"  Ingest Mode: {config.get('ingest_mode', DEFAULT_INGEST_MODE)}")
        print(f"  Document ID: {config.get('document_id') or '(derived from PDF)'}")
    if config["mode"] == "query-only" and config.get("json_output"):
        print(f"  Output    : {config['json_output']}")
    if config["mode"] == "full-pipeline" and config.get("artifact_dir"):
        print(f"  Artifact Dir: {config['artifact_dir']}")
    print(f"  Verbose   : {'on' if config.get('verbose') else 'off'}")
    if config.get("confirm_existing_collection"):
        print("  Risk      : existing collection confirmed")
    print("--------------------")

    if not is_tty:
        return True

    while True:
        raw = input("Proceed? [Y/n] (n = edit): ").strip().lower()
        if raw in ("", "y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Please enter Y or n.")
