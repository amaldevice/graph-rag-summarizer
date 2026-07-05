# Handoff — multi-provider LLM fallback implementation (COMPLETED)

Date: 2026-07-05
Status: Implementation complete. Issues #18 and #19 closed.

## Session summary

This session implemented the full multi-provider LLM fallback for summarization end-to-end.

Both child issues (#18, #19) are implemented and closed. The provider router supports Groq, Gemini, NVIDIA NIM, and OpenRouter with fallback, retry, sticky failover, and a Shared LLM Session reused across map summarization and final reduction.

## What was built

### Provider router

- `summarizer/provider_router.py` — the core module:
  - `ProviderRouter` class — run-scoped Shared LLM Session
  - `resolve_chain()` — builds ordered provider list from config, skips unavailable providers, warns on unknown names
  - `call_llm(system_prompt, user_prompt)` — tries providers in order with fallback
  - `_call_with_retry(provider, ...)` — retry logic for transient failures (max 2 retries, exponential backoff)
  - `_call_provider(provider, ...)` — dispatches to provider-specific client (OpenAI-compatible for Groq/NVIDIA/OpenRouter, native google-genai for Gemini)
  - `_is_auth_error(error)` — detects 401/403/auth failures (skip retry)
  - `_is_transient(error)` — detects rate limits, timeouts, server errors (retry eligible)
  - `_is_hard_failure(response_text, error)` — empty/whitespace output = failure
  - `_get_client(provider)` — lazily creates and caches provider clients
  - `_get_model(provider)` — returns provider-specific model from config
  - `create_session(...)` — factory function for new Shared LLM Sessions
  - `SUPPORTED_PROVIDERS` — ("groq", "gemini", "nvidia", "openrouter")
  - `MAX_RETRIES` = 2, `RETRY_BASE_DELAY` = 1.0, `RETRY_MAX_DELAY` = 8.0

### Summarizer and reducer

- `summarizer/llm_summarizer.py` — rewritten:
  - `LLMSummarizer(session)` — accepts optional ProviderRouter session
  - `summarize_prompt(prompt)` — calls `session.call_llm()`
  - `summarize_communities(community_prompts)` — iterates communities, calls summarize_prompt
  - `save_map_summaries_json/txt(...)` — unchanged output methods

- `summarizer/hierarchical_reducer.py` — rewritten:
  - `HierarchicalReducer(session)` — accepts optional ProviderRouter session
  - `build_reduce_prompt(...)` — unchanged prompt builder
  - `reduce_summaries(...)` — calls `session.call_llm()` instead of local Groq client
  - `save_final_summary_json/txt(...)` — unchanged output methods

### Configuration

- `config/settings.py` — added at bottom:
  - `LLM_PROVIDER` — preferred provider (default: "groq")
  - `LLM_ENABLE_FALLBACK` — toggle (default: True)
  - `LLM_FALLBACK_CHAIN` — parsed list (default: ["groq", "gemini", "nvidia", "openrouter"])
  - `LLM_REQUEST_TIMEOUT_SECONDS` — global timeout (default: 30)
  - `GROQ_API_KEY`, `GROQ_MODEL` (default: "openai/gpt-oss-120b")
  - `GEMINI_API_KEY`, `GEMINI_MODEL` (default: "gemini-2.0-flash")
  - `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_MODEL`, `NVIDIA_NIM_BASE_URL`
  - `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`

- `pyproject.toml` — added dependencies:
  - `google-genai==2.10.0`
  - `openai==2.44.0`

- `env.example` — expanded LLM PROVIDER section with all provider settings

- `README.md` — added Multi-Provider LLM Fallback section

## Architecture decisions

- One ProviderRouter module, not a repository-wide LLM rewrite
- Groq + NVIDIA NIM + OpenRouter share one OpenAI-compatible client path (openai Python SDK)
- Gemini uses native google-genai SDK
- Missing API keys = skip provider with warning; invalid provider names = warn and ignore
- Empty/whitespace output = hard failure triggers failover
- Auth errors (401, 403, "invalid api key") skip retry and go straight to failover
- Transient errors (429, rate, timeout, 500/502/503/504) get up to 2 retries with exponential backoff
- Sticky failover: once failover happens, the rest of the run stays on the recovered provider
- Shared LLM Session: both LLMSummarizer and HierarchicalReducer accept and reuse the same ProviderRouter instance
- Relation extraction (graph/entity_extractor.py) intentionally untouched in this pass
- No launcher changes; config is env-driven only

## Tests

117 tests passing, 0 failures. New test files:

- `tests/test_provider_router.py` — 21 tests:
  - Chain resolution: configured providers, skip missing keys, warn unknown names, warn unknown preferred, empty chain, preferred-first ordering, cache
  - Call behavior: success, fallback on failure, all-providers-fail, disabled fallback, empty output, whitespace output
  - Sticky failover, no providers available, auth error skip retry, transient retry before failover
  - is_configured, get_model, failure_history, is_hard_failure

- `tests/test_shared_session.py` — 6 tests:
  - Shared session identity, sticky failover across stages, Groq-only backward compatibility
  - Summarizer output format, reducer output format, reducer prompt builder

## GitHub status

- Issue #18 (provider-routed map summarization): closed with implementation comment
- Issue #19 (shared provider session for reduction): closed with implementation comment
- Issue #17 (parent PRD): still open

## Current repo state

- Branch: main
- Working tree has uncommitted changes (all multi-provider implementation)
- Modified files: README.md, config/settings.py, env.example, pyproject.toml, uv.lock, summarizer/llm_summarizer.py, summarizer/hierarchical_reducer.py, docs/todo-in-progress.md, docs/completed/completed-tasks.md, CONTEXT.md, .gitignore
- New files: summarizer/provider_router.py, tests/test_provider_router.py, tests/test_shared_session.py
- Archived handoff: docs/completed/handoffs/handoff-2026-07-05-multi-provider-llm-fallback-implementation.md
- Planning docs from prior session still present (docs/prd-..., docs/slice-...)
- Personal files untouched
- .env contains real credentials — do not echo or commit

## What still needs doing

### Immediate

- Commit the implementation and push
- Close or update parent issue #17
- Archive planning docs to docs/completed/prd/ and docs/completed/issues/

### Follow-up candidates (not implemented)

- Route relation extraction through multi-provider fallback (phase 2)
- Per-provider timeout settings instead of global timeout
- OpenRouter attribution headers
- Provider health probes at menu time
- Cost-based or latency-based dynamic routing

## Minimal pickup prompt for the next agent

"The multi-provider LLM fallback implementation is complete. Issues #18 and #19 are closed. Commit the changes, close or update parent issue #17, and archive the planning docs. Relation extraction stays out of scope for this pass."
