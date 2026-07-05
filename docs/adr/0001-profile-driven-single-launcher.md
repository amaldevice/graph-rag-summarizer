# Use a profile-driven single launcher with session-only overrides

The project will treat `main.py` as the human-facing launcher for Ingest Runs, Query-Only Runs, and Full-Pipeline Runs. We will keep credentials plus Stable Defaults in repository configuration, resolve per-run choices through CLI flags or an interactive wizard, and apply Launch Profile choices as Session Overrides instead of rewriting `.env`. This keeps automation compatible with existing entrypoints while giving human operators one predictable runtime surface.
