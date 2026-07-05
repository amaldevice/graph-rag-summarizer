# ============================================================
# PROVIDER ROUTER
# Run-scoped LLM provider routing with fallback, retry,
# and sticky failover for summarization work.
# ============================================================

import time
import warnings
from typing import Optional

from config import settings

SUPPORTED_PROVIDERS = ("groq", "gemini", "nvidia", "openrouter")
MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 8.0
AUTH_ERROR_MARKERS = ("401", "403", "unauthorized", "invalid api key", "permission denied", "authentication")


class ProviderRouter:
    """A run-scoped Shared LLM Session that manages provider selection,
    fallback, retry, and sticky failover for one summarization run."""

    def __init__(
        self,
        preferred_provider: Optional[str] = None,
        fallback_chain: Optional[list[str]] = None,
        enable_fallback: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.preferred_provider = (preferred_provider or settings.LLM_PROVIDER).strip().lower()
        self.enable_fallback = enable_fallback if enable_fallback is not None else settings.LLM_ENABLE_FALLBACK
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.LLM_REQUEST_TIMEOUT_SECONDS

        if fallback_chain is not None:
            self.configured_chain = [p.lower().strip() for p in fallback_chain if p.strip()]
        else:
            self.configured_chain = list(settings.LLM_FALLBACK_CHAIN)

        self._active_provider: Optional[str] = None
        self._failed_providers: set[str] = set()
        self._failure_history: list[dict] = []
        self._clients: dict = {}
        self._resolved_chain: Optional[list[str]] = None

    @property
    def active_provider(self) -> Optional[str]:
        return self._active_provider

    @property
    def failure_history(self) -> list[dict]:
        return list(self._failure_history)

    def resolve_chain(self) -> list[str]:
        """Build the resolved provider chain, skipping unavailable providers."""
        if self._resolved_chain is not None:
            return self._resolved_chain

        chain = []
        for name in self.configured_chain:
            if name not in SUPPORTED_PROVIDERS:
                warnings.warn(f"Unknown LLM provider '{name}' ignored.", stacklevel=2)
                continue
            missing_fields = self._missing_config_fields(name)
            if missing_fields:
                warnings.warn(
                    f"LLM provider '{name}' skipped: missing configuration ({', '.join(missing_fields)}).",
                    stacklevel=2,
                )
                continue
            chain.append(name)

        if self.preferred_provider not in SUPPORTED_PROVIDERS:
            warnings.warn(
                f"Unknown preferred provider '{self.preferred_provider}' ignored.",
                stacklevel=2,
            )
        elif self.preferred_provider not in chain and self._is_configured(self.preferred_provider):
            chain.insert(0, self.preferred_provider)

        if not chain:
            self._resolved_chain = []
            return self._resolved_chain

        if self.preferred_provider in chain and chain[0] != self.preferred_provider:
            chain.remove(self.preferred_provider)
            chain.insert(0, self.preferred_provider)

        self._resolved_chain = chain
        return self._resolved_chain

    def _required_config(self, provider: str) -> list[tuple[str, str]]:
        if provider == "groq":
            return [
                ("GROQ_API_KEY", settings.GROQ_API_KEY),
                ("GROQ_MODEL", settings.GROQ_MODEL),
            ]
        if provider == "gemini":
            return [
                ("GEMINI_API_KEY", settings.GEMINI_API_KEY),
                ("GEMINI_MODEL", settings.GEMINI_MODEL),
            ]
        if provider == "nvidia":
            return [
                ("NVIDIA_NIM_API_KEY", settings.NVIDIA_NIM_API_KEY),
                ("NVIDIA_NIM_MODEL", settings.NVIDIA_NIM_MODEL),
                ("NVIDIA_NIM_BASE_URL", settings.NVIDIA_NIM_BASE_URL),
            ]
        if provider == "openrouter":
            return [
                ("OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY),
                ("OPENROUTER_MODEL", settings.OPENROUTER_MODEL),
                ("OPENROUTER_BASE_URL", settings.OPENROUTER_BASE_URL),
            ]
        return []

    def _missing_config_fields(self, provider: str) -> list[str]:
        return [name for name, value in self._required_config(provider) if not str(value).strip()]

    def _is_configured(self, provider: str) -> bool:
        return not self._missing_config_fields(provider)

    def _get_client(self, provider: str):
        """Lazily create and cache the client for a provider."""
        if provider in self._clients:
            return self._clients[provider]

        if provider == "groq":
            from groq import Groq
            client = Groq(api_key=settings.GROQ_API_KEY, timeout=self.timeout_seconds)
        elif provider == "gemini":
            from google import genai
            client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options={"timeout": self.timeout_seconds * 1000},
            )
        elif provider == "nvidia":
            from openai import OpenAI
            client = OpenAI(
                api_key=settings.NVIDIA_NIM_API_KEY,
                base_url=settings.NVIDIA_NIM_BASE_URL,
                timeout=self.timeout_seconds,
            )
        elif provider == "openrouter":
            from openai import OpenAI
            client = OpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_BASE_URL,
                timeout=self.timeout_seconds,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        self._clients[provider] = client
        return client

    def _get_model(self, provider: str) -> str:
        if provider == "groq":
            return settings.GROQ_MODEL
        elif provider == "gemini":
            return settings.GEMINI_MODEL
        elif provider == "nvidia":
            return settings.NVIDIA_NIM_MODEL
        elif provider == "openrouter":
            return settings.OPENROUTER_MODEL
        raise ValueError(f"Unknown provider: {provider}")

    def _call_provider(self, provider: str, system_prompt: str, user_prompt: str) -> str:
        """Call a single provider and return the response text."""
        client = self._get_client(provider)
        model = self._get_model(provider)

        if provider == "gemini":
            from google.genai import types
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=400,
                ),
            )
            text = response.text or ""
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_completion_tokens=400,
            )
            text = response.choices[0].message.content or ""

        return text.strip()

    def _is_auth_error(self, error: Exception) -> bool:
        error_text = str(error).lower()
        return any(marker in error_text for marker in AUTH_ERROR_MARKERS)

    def _is_transient(self, error: Exception) -> bool:
        error_text = str(error).lower()
        if self._is_auth_error(error):
            return False
        return any(kw in error_text for kw in (
            "429", "rate", "limit", "timeout", "timed out",
            "500", "502", "503", "504",
            "server", "overloaded", "try again",
        ))

    def _is_hard_failure(self, response_text: str, error: Optional[Exception] = None) -> bool:
        """Determine if a result constitutes a hard failure."""
        if error is not None:
            return True
        if not response_text or not response_text.strip():
            return True
        return False

    def call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM with fallback. Returns response text or raises RuntimeError."""
        if not self.enable_fallback:
            if self.preferred_provider not in SUPPORTED_PROVIDERS:
                raise RuntimeError(
                    f"Preferred LLM provider '{self.preferred_provider}' is unknown. "
                    f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}."
                )
            missing_fields = self._missing_config_fields(self.preferred_provider)
            if missing_fields:
                raise RuntimeError(
                    f"Preferred LLM provider '{self.preferred_provider}' is unavailable: "
                    f"missing configuration ({', '.join(missing_fields)})."
                )
            result = self._call_with_retry(self.preferred_provider, system_prompt, user_prompt)
            self._active_provider = self.preferred_provider
            return result

        chain = self.resolve_chain()

        if not chain:
            raise RuntimeError("No LLM providers available. Check API keys in configuration.")

        remaining = [p for p in chain if p not in self._failed_providers]
        if not remaining:
            remaining = list(chain)

        last_error = None
        for provider in remaining:
            try:
                result = self._call_with_retry(provider, system_prompt, user_prompt)
                self._active_provider = provider
                return result
            except Exception as e:
                last_error = e
                self._failed_providers.add(provider)
                self._failure_history.append({
                    "provider": provider,
                    "error": str(e),
                })
                print(f"  ⚠ Provider '{provider}' failed: {e}")
                continue

        failed_summary = "; ".join(
            f"{f['provider']}: {f['error']}" for f in self._failure_history
        )
        raise RuntimeError(
            f"All LLM providers failed. Failure summary: [{failed_summary}]"
        )

    def _call_with_retry(self, provider: str, system_prompt: str, user_prompt: str) -> str:
        """Call a provider with retry logic for transient failures."""
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                result = self._call_provider(provider, system_prompt, user_prompt)
                if self._is_hard_failure(result):
                    raise RuntimeError(f"Provider '{provider}' returned empty response")
                return result
            except Exception as e:
                last_error = e
                if self._is_auth_error(e):
                    raise
                if not self._is_transient(e):
                    raise
                if attempt < MAX_RETRIES:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    time.sleep(delay)
                    continue

        raise last_error


def create_session(
    preferred_provider: Optional[str] = None,
    fallback_chain: Optional[list[str]] = None,
    enable_fallback: Optional[bool] = None,
    timeout_seconds: Optional[int] = None,
) -> ProviderRouter:
    """Create a new Shared LLM Session for one run."""
    return ProviderRouter(
        preferred_provider=preferred_provider,
        fallback_chain=fallback_chain,
        enable_fallback=enable_fallback,
        timeout_seconds=timeout_seconds,
    )
