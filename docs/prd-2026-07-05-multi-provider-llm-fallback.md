# PRD — multi-provider LLM fallback for summarization runs

Date: 2026-07-05
Status: Published as issue #17

## Problem Statement

The repository currently treats Groq as the only practical LLM backend for summarization work. A run that reaches map summarization or final reduction depends on one provider path, one API key, and one provider-specific client shape.

From a user perspective, this creates three avoidable problems:

- one provider outage, timeout burst, or rate-limit event can block a full summarization run even when other providers are available,
- users who fork the repository cannot choose the provider mix that best matches their credits, latency, or regional availability without editing code,
- and the current summarization path does not separate Stable Defaults from run-scoped provider recovery behavior.

The project already supports local-versus-cloud storage and vector infrastructure as explicit runtime choices. The LLM layer still behaves like a single hardcoded dependency, which makes the summarization pipeline more brittle than the rest of the system.

## Solution

Add a provider-routed LLM layer for summarization runs with four supported providers:

1. Groq
2. Gemini
3. NVIDIA NIM
4. OpenRouter

The first pass should keep the product surface intentionally narrow:

- scope the new router to map summarization and final reduction only,
- keep relation extraction outside the multi-provider contract for now,
- keep configuration env-driven instead of adding new launcher prompts,
- use a Shared LLM Session per run so map summarization and final reduction share the same provider state,
- start from a Preferred Provider and optionally recover through a Fallback Chain,
- and treat fallback as an availability mechanism rather than a quality-judging mechanism.

The default recovery order should be:

`groq -> gemini -> nvidia -> openrouter`

Users may override the Preferred Provider and Fallback Chain through environment configuration, while keeping provider credentials and default model choices in Stable Defaults.

## User Stories

1. As a summarization operator, I want the run to start from a Preferred Provider, so that I can bias toward the provider I trust most.
2. As a summarization operator, I want a default Fallback Chain, so that temporary provider failures do not immediately kill a full run.
3. As a fork user, I want to change the Preferred Provider through environment configuration, so that I do not need to patch repository code for my own API accounts.
4. As a fork user, I want to override the Fallback Chain through environment configuration, so that I can match my own cost and availability priorities.
5. As a user, I want providers with missing API keys to be skipped automatically, so that partial configuration does not block all summarization work.
6. As a user, I want unknown provider names in the configured chain to be ignored with a warning, so that one typo does not crash startup.
7. As a user, I want Groq, Gemini, NVIDIA NIM, and OpenRouter each to have their own default model setting, so that cross-provider fallback does not depend on one global model string.
8. As a user, I want the system to retry short-lived provider failures briefly before failing over, so that transient outages do not trigger unnecessary provider switching.
9. As a user, I want authentication and configuration errors to skip retry and move straight to failover, so that obviously broken providers do not waste time.
10. As a user, I want a global timeout for each LLM request, so that one slow provider does not hang the run indefinitely.
11. As a user, I want empty text responses treated as failures, so that a provider cannot silently return unusable output.
12. As a user, I want fallback to happen only on Hard Failure, so that a merely different writing style does not unpredictably switch providers.
13. As a user, I want the failover decision to become sticky for the rest of that run, so that later steps do not bounce back and forth between providers.
14. As a user, I want the final reducer to reuse the same Shared LLM Session as map summarization, so that one run stays behaviorally consistent.
15. As a user, I want the system to summarize all provider failures when every provider is exhausted, so that I can diagnose the real blocker quickly.
16. As a user, I want to disable fallback globally, so that I can run deterministic single-provider comparisons or debugging sessions.
17. As a user, I want fallback-disabled mode to try only the configured Preferred Provider, so that the behavior matches the explicit configuration intent.
18. As a user, I want the default Fallback Chain to begin with Groq, so that existing repository behavior remains the first attempted path.
19. As a user, I want Gemini support to use the native Google GenAI SDK, so that Gemini remains available even if its OpenAI-compatible route is not the preferred path.
20. As a user, I want Groq, NVIDIA NIM, and OpenRouter to share one OpenAI-compatible client path, so that the provider layer stays small and maintainable.
21. As a maintainer, I want relation extraction kept outside this first-pass router, so that structured JSON extraction risk does not expand the scope of summarization recovery work.
22. As a maintainer, I want the provider router driven by Stable Defaults in configuration, so that launcher behavior does not need a new interactive branch yet.
23. As a maintainer, I want the router to expose concise provider logs, so that fallback behavior is debuggable without becoming noisy.
24. As a maintainer, I want map summarization and final reduction to consume the same provider abstraction, so that future provider additions touch one seam instead of many.
25. As a maintainer, I want the default path to keep working when only Groq is configured, so that the new router is backward-compatible with existing setups.
26. As a maintainer, I want tests around provider ordering, retry classification, sticky failover, and all-provider failure summaries, so that fallback regressions fail fast.
27. As a maintainer, I want provider-specific details such as OpenRouter attribution headers to stay out of scope for the first pass, so that the initial integration stays narrow.
28. As a collaborator, I want the env contract documented clearly, so that I can onboard without reading implementation code first.
29. As a collaborator, I want the repository docs to explain which LLM surfaces are covered by the router and which are not, so that expectations stay accurate.
30. As a collaborator, I want a single published parent issue plus execution slices, so that later agents can implement the feature without reconstructing the design from chat history.

## Implementation Decisions

- The first pass introduces one run-scoped provider router for summarization work, not a repository-wide LLM rewrite.
- The provider router covers two summarization surfaces only: community map summarization and final reduction.
- Relation extraction remains on its current path in the first pass because it depends on strict structured output and already has a non-LLM fallback behavior.
- The provider router exposes a Shared LLM Session that carries Preferred Provider selection, resolved Fallback Chain order, sticky failover state, retry policy, timeout policy, and failure history for one run.
- Fallback is triggered only by Hard Failure categories such as timeout, rate limit, transient server failure, invalid auth, malformed output, or empty output. It is not triggered by subjective quality differences.
- When fallback is enabled, the router begins with the configured Preferred Provider and then walks the rest of the resolved Fallback Chain exactly once per provider until a provider succeeds or the chain is exhausted.
- When fallback is disabled, the router tries only the Preferred Provider and surfaces its failure directly.
- Providers missing required credentials or configuration are treated as unavailable and skipped with a concise warning rather than blocking startup.
- Unknown provider names in configured env values are ignored with a warning instead of aborting the run.
- Groq, NVIDIA NIM, and OpenRouter share one OpenAI-compatible chat-completions client path.
- Gemini uses the native Google GenAI SDK path in the first pass.
- Each provider receives its own default model setting and API-key env name instead of sharing one global model string.
- The router uses one global request-timeout setting in the first pass rather than a per-provider timeout matrix.
- Retry policy stays intentionally small: transient failures get at most two retries with a short exponential backoff before failover; invalid auth and invalid configuration skip retry.
- An empty or whitespace-only provider response is treated as a failure condition.
- The final reducer must reuse the same Shared LLM Session selected during map summarization so later stages inherit sticky failover state rather than recomputing provider choice independently.
- Provider logging should be concise and operator-facing: unavailable provider skips, failover events, and final provider selection are visible, but routine successful requests do not emit verbose trace noise.
- The environment contract introduces a Preferred Provider setting, an optional Fallback Chain override, a global fallback toggle, a global request timeout, and provider-specific credential/model settings.
- The first pass keeps user-facing control env-driven only; no new launcher prompt is added for provider selection.

## Testing Decisions

- Good tests should verify observable provider-routing behavior rather than SDK internals.
- The highest-value seam is the shared summarization provider router: given configuration and provider outcomes, the run should resolve provider order, retries, failover, and failure summaries deterministically.
- Add contract tests for provider-order resolution, missing-key skips, invalid-provider warnings, fallback-disabled behavior, retry classification, timeout handling, sticky failover, and all-provider failure summaries.
- Add map-summarization tests that prove a successful fallback provider can produce summaries after an earlier provider fails.
- Add final-reduction tests that prove the reducer reuses the same Shared LLM Session rather than resolving providers independently.
- Add regression coverage for backward compatibility when only Groq is configured.
- Add docs/env-contract tests only where the codebase already checks outward-facing configuration behavior; avoid asserting documentation prose.
- Prior art should come from the existing contract-style tests around the launcher, full-pipeline dispatch, and embedding-runtime resolution, because those tests already favor behavioral seams over implementation details.

## Out of Scope

- Routing relation extraction through the multi-provider fallback chain.
- Adding provider-selection prompts to the launcher wizard.
- Using fallback to chase better output quality rather than service availability.
- Persisting failover state across runs.
- OpenRouter attribution headers and other provider-specific metadata extras.
- Streaming, tool-calling, multimodal, or structured-output feature parity across providers.
- A repository-wide migration of every current or future LLM touchpoint into the new router.
- Cost-based, latency-based, or health-probe-based dynamic routing policies.

## Further Notes

- The first pass should stay boring: one provider router, one Shared LLM Session, one env contract, and the smallest number of provider-specific code paths.
- The design intentionally optimizes for operational resilience while preserving the current Groq-first default.
- A later follow-up can revisit relation extraction once the plain-text summarization path proves stable across multiple providers.
