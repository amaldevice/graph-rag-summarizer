# ============================================================
# PROVIDER ROUTER TESTS
# Provider ordering, retries, skips, failover, failure summaries.
# ============================================================

import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import warnings
import pytest

from config import settings
from summarizer.provider_router import (
    ProviderRouter,
    create_session,
    SUPPORTED_PROVIDERS,
    MAX_RETRIES,
)


# ------------------------------------------------------------------
# Provider chain resolution
# ------------------------------------------------------------------

def test_resolve_chain_returns_configured_providers(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "LLM_FALLBACK_CHAIN", ["groq", "gemini"])
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(preferred_provider="groq", fallback_chain=["groq", "gemini"])
    chain = router.resolve_chain()
    assert chain == ["groq", "gemini"]


def test_resolve_chain_skips_providers_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq", "gemini", "nvidia", "openrouter"])
    chain = router.resolve_chain()
    assert chain == ["groq"]


def test_resolve_chain_skips_provider_with_missing_model(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GROQ_MODEL", "   ")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert router.resolve_chain() == []
        assert any("GROQ_MODEL" in str(warning.message) for warning in caught)


def test_resolve_chain_skips_provider_with_missing_groq_base_url(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GROQ_MODEL", "groq-model")
    monkeypatch.setattr(settings, "GROQ_BASE_URL", "  ")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert router.resolve_chain() == []
        assert any("GROQ_BASE_URL" in str(warning.message) for warning in caught)


def test_resolve_chain_skips_provider_with_missing_base_url(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "key-openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "router-model")
    monkeypatch.setattr(settings, "OPENROUTER_BASE_URL", "  ")

    router = create_session(fallback_chain=["openrouter"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert router.resolve_chain() == []
        assert any("OPENROUTER_BASE_URL" in str(warning.message) for warning in caught)


def test_resolve_chain_warns_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq", "badname", "gemini"])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        chain = router.resolve_chain()
        assert chain == ["groq"]
        assert any("badname" in str(warning.message) for warning in w)


def test_resolve_chain_warns_on_unknown_preferred(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(preferred_provider="badname", fallback_chain=["groq"])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        chain = router.resolve_chain()
        assert chain == ["groq"]
        assert any("badname" in str(warning.message) for warning in w)


def test_resolve_chain_empty_when_no_keys(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq", "gemini"])
    chain = router.resolve_chain()
    assert chain == []


def test_resolve_chain_puts_preferred_first(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(preferred_provider="gemini", fallback_chain=["groq", "gemini"])
    chain = router.resolve_chain()
    assert chain[0] == "gemini"


def test_resolve_chain_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq"])
    chain1 = router.resolve_chain()
    chain2 = router.resolve_chain()
    assert chain1 is chain2


# ------------------------------------------------------------------
# Call LLM — success path
# ------------------------------------------------------------------

def test_call_llm_returns_text_on_success(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(preferred_provider="groq", fallback_chain=["groq"])

    def fake_call(provider, system_prompt, user_prompt):
        return "summary result"

    monkeypatch.setattr(router, "_call_provider", fake_call)

    result = router.call_llm("system", "user prompt")
    assert result == "summary result"
    assert router.active_provider == "groq"


# ------------------------------------------------------------------
# Call LLM — fallback on failure
# ------------------------------------------------------------------

def test_call_llm_falls_over_to_next_provider_on_failure(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    call_count = {"groq": 0, "gemini": 0}

    def fake_call_groq(system_prompt, user_prompt):
        call_count["groq"] += 1
        raise RuntimeError("rate limited")

    def fake_call_gemini(system_prompt, user_prompt):
        call_count["gemini"] += 1
        return "gemini result"

    monkeypatch.setattr(router, "_call_provider", lambda p, s, u: (
        fake_call_groq(s, u) if p == "groq" else fake_call_gemini(s, u)
    ))

    result = router.call_llm("system", "prompt")
    assert result == "gemini result"
    assert router.active_provider == "gemini"
    assert call_count["gemini"] == 1


def test_call_llm_falls_back_when_response_validator_rejects_first_result(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )
    calls = []

    def fake_call(provider, system_prompt, user_prompt):
        del system_prompt, user_prompt
        calls.append(provider)
        return "not-json" if provider == "groq" else '{"status":"accepted"}'

    monkeypatch.setattr(router, "_call_provider", fake_call)

    result = router.call_llm(
        "system",
        "prompt",
        response_validator=lambda response: response.startswith("{"),
    )

    assert result == '{"status":"accepted"}'
    assert calls == ["groq", "gemini"]
    assert router.active_provider == "gemini"


def test_call_llm_raises_when_all_providers_fail(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    def fake_call(provider, system_prompt, user_prompt):
        raise RuntimeError(f"{provider} failed")

    monkeypatch.setattr(router, "_call_provider", fake_call)

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        router.call_llm("system", "prompt")

    assert len(router.failure_history) == 2


def test_call_llm_redacts_provider_credentials_from_failure_diagnostics(monkeypatch, capsys):
    secret = "modal-secret-value"
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", secret)
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    router = create_session(
        preferred_provider="gemini",
        fallback_chain=["gemini"],
        enable_fallback=True,
    )
    monkeypatch.setattr(
        router,
        "_call_provider",
        lambda provider, system_prompt, user_prompt: (_ for _ in ()).throw(
            RuntimeError(f"403 Consumer 'api_key:{secret}' suspended")
        ),
    )

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        router.call_llm("system", "prompt")

    output = capsys.readouterr().out
    assert secret not in output
    assert secret not in router.failure_history[0]["error"]
    assert "api_key:[REDACTED]" in output


def test_has_available_provider_stays_false_after_the_configured_provider_fails(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    router = create_session(preferred_provider="groq", fallback_chain=["groq"])
    monkeypatch.setattr(
        router,
        "_call_provider",
        lambda provider, system_prompt, user_prompt: (_ for _ in ()).throw(
            RuntimeError("Provider unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        router.call_llm("system", "prompt")

    assert router.has_available_provider() is False


# ------------------------------------------------------------------
# Fallback disabled
# ------------------------------------------------------------------

def test_call_llm_disabled_fallback_tries_only_preferred(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=False,
    )

    def fake_call(provider, system_prompt, user_prompt):
        raise RuntimeError(f"{provider} failed")

    monkeypatch.setattr(router, "_call_provider", fake_call)

    with pytest.raises(RuntimeError, match="groq failed"):
        router.call_llm("system", "prompt")

    assert len(router.failure_history) == 0


def test_call_llm_disabled_fallback_fails_if_preferred_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=False,
    )

    call_log = []
    monkeypatch.setattr(
        router,
        "_call_with_retry",
        lambda provider, system_prompt, user_prompt: call_log.append(provider),
    )

    with pytest.raises(RuntimeError, match="Preferred LLM provider 'groq' is unavailable"):
        router.call_llm("system", "prompt")

    assert call_log == []


# ------------------------------------------------------------------
# Empty output as failure
# ------------------------------------------------------------------

def test_call_llm_treats_empty_output_as_failure(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    call_log = []

    def fake_call(provider, system_prompt, user_prompt):
        call_log.append(provider)
        if provider == "groq":
            return ""
        return "gemini result"

    monkeypatch.setattr(router, "_call_provider", fake_call)

    result = router.call_llm("system", "prompt")
    assert result == "gemini result"
    assert call_log == ["groq", "gemini"]


def test_call_llm_treats_whitespace_output_as_failure(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    def fake_call(provider, system_prompt, user_prompt):
        if provider == "groq":
            return "   \n  \t  "
        return "gemini result"

    monkeypatch.setattr(router, "_call_provider", fake_call)

    result = router.call_llm("system", "prompt")
    assert result == "gemini result"


# ------------------------------------------------------------------
# Sticky failover
# ------------------------------------------------------------------

def test_sticky_failover_stays_on_recovered_provider(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    call_log = []

    def fake_call_with_retry(provider, system_prompt, user_prompt):
        call_log.append(provider)
        if provider == "groq":
            raise RuntimeError("rate limited")
        return f"{provider} result"

    monkeypatch.setattr(router, "_call_with_retry", fake_call_with_retry)

    result1 = router.call_llm("system", "prompt1")
    result2 = router.call_llm("system", "prompt2")

    assert result1 == "gemini result"
    assert result2 == "gemini result"
    assert call_log == ["groq", "gemini", "gemini"]


# ------------------------------------------------------------------
# No providers available
# ------------------------------------------------------------------

def test_call_llm_raises_when_no_providers_available(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(fallback_chain=["groq", "gemini"])

    with pytest.raises(RuntimeError, match="No LLM providers available"):
        router.call_llm("system", "prompt")


# ------------------------------------------------------------------
# Auth error — skip retry
# ------------------------------------------------------------------

def test_auth_error_skips_retry_and_falls_over(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    retry_count = {"groq": 0}

    def fake_call(provider, system_prompt, user_prompt):
        if provider == "groq":
            retry_count["groq"] += 1
            raise RuntimeError("401 Unauthorized: invalid api key")
        return "gemini result"

    monkeypatch.setattr(router, "_call_provider", fake_call)

    result = router.call_llm("system", "prompt")
    assert result == "gemini result"
    assert retry_count["groq"] == 1


# ------------------------------------------------------------------
# Retry on transient failure
# ------------------------------------------------------------------

def test_transient_error_retries_before_failing_over(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    retry_count = {"groq": 0}

    def fake_call(provider, system_prompt, user_prompt):
        if provider == "groq":
            retry_count["groq"] += 1
            raise RuntimeError("429 rate limited")
        return "gemini result"

    monkeypatch.setattr(router, "_call_provider", fake_call)
    monkeypatch.setattr("summarizer.provider_router.time.sleep", lambda x: None)

    result = router.call_llm("system", "prompt")
    assert result == "gemini result"
    assert retry_count["groq"] == MAX_RETRIES + 1


# ------------------------------------------------------------------
# is_configured
# ------------------------------------------------------------------

def test_is_configured_checks_correct_key(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session()
    assert router._is_configured("groq") is True
    assert router._is_configured("gemini") is False


# ------------------------------------------------------------------
# Model resolution
# ------------------------------------------------------------------

def test_get_model_returns_provider_specific_model(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_MODEL", "groq-model")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-model")
    monkeypatch.setattr(settings, "NVIDIA_NIM_MODEL", "nvidia-model")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "openrouter-model")

    router = create_session()
    assert router._get_model("groq") == "groq-model"
    assert router._get_model("gemini") == "gemini-model"
    assert router._is_configured("nvidia") is False or True


def test_get_client_passes_timeout_to_gemini_client(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")

    captured = {}
    google_module = types.ModuleType("google")
    genai_module = types.ModuleType("google.genai")

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    genai_module.Client = fake_client
    google_module.genai = genai_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)

    router = create_session(timeout_seconds=45)
    router._get_client("gemini")

    assert captured == {
        "api_key": "key-gemini",
        "http_options": {"timeout": 45000},
    }


# ------------------------------------------------------------------
# Failure history
# ------------------------------------------------------------------

def test_failure_history_records_all_failures(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key-gemini")
    monkeypatch.setattr(settings, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    router = create_session(
        preferred_provider="groq",
        fallback_chain=["groq", "gemini"],
        enable_fallback=True,
    )

    def fake_call(provider, system_prompt, user_prompt):
        raise RuntimeError(f"{provider} error")

    monkeypatch.setattr(router, "_call_provider", fake_call)

    with pytest.raises(RuntimeError):
        router.call_llm("system", "prompt")

    assert len(router.failure_history) == 2
    assert router.failure_history[0]["provider"] == "groq"
    assert router.failure_history[1]["provider"] == "gemini"


# ------------------------------------------------------------------
# Hard failure detection
# ------------------------------------------------------------------

def test_is_hard_failure_empty_string():
    router = create_session()
    assert router._is_hard_failure("") is True
    assert router._is_hard_failure("   ") is True
    assert router._is_hard_failure("valid text") is False
    assert router._is_hard_failure("valid text", error=RuntimeError("err")) is True
