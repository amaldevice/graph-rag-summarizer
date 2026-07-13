# ============================================================
# SINGLE LAUNCHER
# Human-facing entrypoint for Ingest, Query-Only,
# and Full-Pipeline runs.
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import os
import sys
from types import SimpleNamespace

from config.settings import ENABLE_PERSISTENT_GRAPH

from launcher.contract import (
    build_cli_parser,
    check_availability,
    resolve_mode,
    resolve_profile,
    run_interactive_wizard,
    show_summary_and_confirm,
)
from launcher.runners import run_full_pipeline, run_ingest, run_query_only


def _apply_profile_session_overrides(profile: str) -> None:
    os.environ["LAUNCHER_PROFILE"] = profile
    if profile == "local":
        os.environ["QDRANT_BACKEND"] = "local"
        os.environ["STORAGE_BACKEND"] = "minio"
    elif profile == "cloud":
        os.environ["QDRANT_BACKEND"] = "cloud"
        os.environ["STORAGE_BACKEND"] = "r2"


def _config_to_args(config: dict, profile_locked: bool) -> SimpleNamespace:
    return SimpleNamespace(
        mode=config["mode"],
        profile=config["profile"] if profile_locked else None,
        collection=config.get("collection") or None,
        query=config.get("query") or None,
        retrieval_limit=config.get("retrieval_limit"),
        pdf=config.get("pdf_path") or None,
        no_interactive=False,
        json_output=config.get("json_output") or None,
        artifact_dir=config.get("artifact_dir") or None,
        verbose=config.get("verbose", False),
        confirm_existing_collection=config.get("confirm_existing_collection", False),
        ingest_mode=config.get("ingest_mode"),
        document_id=config.get("document_id") or None,
        enable_graph_artifact=config.get("enable_graph_artifact", ENABLE_PERSISTENT_GRAPH),
    )


def main():
    parser = build_cli_parser()
    args = parser.parse_args()

    is_tty = sys.stdin.isatty()
    interactive_allowed = is_tty and not args.no_interactive

    env_profile = os.getenv("LAUNCHER_PROFILE", "")
    profile = resolve_profile(args.profile, env_profile or None)

    mode = resolve_mode(args.mode)

    if mode is None and not interactive_allowed:
        raise SystemExit("Error: --mode is required in non-interactive mode")

    config = run_interactive_wizard(args, profile, is_tty=interactive_allowed)

    while True:
        _apply_profile_session_overrides(config["profile"])

        missing = check_availability(config["mode"], config["profile"])
        if missing:
            print("\n--- Mode Unavailable ---")
            for item in missing:
                print(f"  - {item}")
            print("------------------------")
            raise SystemExit(1)

        if show_summary_and_confirm(config, interactive_allowed):
            break

        print("Returning to edit mode...")
        config = run_interactive_wizard(
            _config_to_args(config, profile_locked=bool(args.profile)),
            config["profile"],
            is_tty=True,
        )

    mode = config["mode"]
    if mode == "query-only":
        run_query_only(config)
    elif mode == "ingest":
        run_ingest(config)
    elif mode == "full-pipeline":
        run_full_pipeline(config)
    else:
        raise SystemExit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
