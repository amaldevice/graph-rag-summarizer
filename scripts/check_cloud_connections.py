from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

QDRANT_REQUIRED_VARS = (
    "QDRANT_URL",
    "QDRANT_API_KEY",
)

R2_REQUIRED_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)


def get_missing_env_vars(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not os.getenv(name, "").strip()]


def load_env_file(env_file: str) -> Path:
    path = Path(env_file)
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Environment file not found: {path}")
    load_dotenv(path, override=True)
    return path


def check_qdrant_connection(handler_cls=None) -> dict:
    missing = get_missing_env_vars(QDRANT_REQUIRED_VARS)
    if missing:
        raise RuntimeError(f"Missing Qdrant env vars: {', '.join(missing)}")

    if handler_cls is None:
        from vectordb.qdrant_handler import QdrantHandler

        handler_cls = QdrantHandler

    handler = handler_cls(qdrant_backend="cloud")
    collections = handler.client.get_collections().collections
    return {
        "collection_target": os.getenv("QDRANT_COLLECTION", "summarizer_docs"),
        "collections": [collection.name for collection in collections],
    }


def check_r2_connection(handler_cls=None) -> dict:
    missing = get_missing_env_vars(R2_REQUIRED_VARS)
    if missing:
        raise RuntimeError(f"Missing R2 env vars: {', '.join(missing)}")

    if handler_cls is None:
        from storage.r2_handler import R2Handler

        handler_cls = R2Handler

    handler = handler_cls()
    handler.client.head_bucket(Bucket=handler.bucket_name)
    return {
        "bucket": handler.bucket_name,
        "public_base_url": handler.public_base_url,
    }


def run_checks(target: str) -> bool:
    success = True

    if target in {"qdrant", "all"}:
        print("\n== Qdrant Cloud ==")
        try:
            result = check_qdrant_connection()
            print("✅ Connected")
            print(f"   Collection target : {result['collection_target']}")
            print(f"   Existing collections: {len(result['collections'])}")
        except Exception as exc:
            success = False
            print(f"❌ Qdrant check failed: {exc}")

    if target in {"r2", "all"}:
        print("\n== Cloudflare R2 ==")
        try:
            result = check_r2_connection()
            print("✅ Connected")
            print(f"   Bucket          : {result['bucket']}")
            print(f"   Public base URL : {result['public_base_url']}")
        except Exception as exc:
            success = False
            print(f"❌ R2 check failed: {exc}")

    return success


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check cloud connectivity for Qdrant Cloud and Cloudflare R2.",
    )
    parser.add_argument(
        "--env-file",
        default=".env.cloud",
        help="Environment file to load before checking connections (default: .env.cloud)",
    )
    parser.add_argument(
        "--target",
        choices=("all", "qdrant", "r2"),
        default="all",
        help="Which cloud service to check",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_path = load_env_file(args.env_file)
    print(f"Loaded env file: {env_path}")
    return 0 if run_checks(args.target) else 1


if __name__ == "__main__":
    raise SystemExit(main())
