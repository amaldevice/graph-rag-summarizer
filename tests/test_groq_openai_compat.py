import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings
from summarizer.provider_router import create_session
import graph.entity_extractor as entity_extractor_module


def test_provider_router_routes_groq_through_openai_compatible_client(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "key-groq")

    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    import openai

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    router = create_session(timeout_seconds=45)
    client = router._get_client("groq")

    assert client is router._clients["groq"]
    assert captured == {
        "api_key": "key-groq",
        "base_url": "https://api.groq.com/openai/v1",
        "timeout": 45,
    }


def test_entity_extractor_uses_openai_compatible_groq_client(monkeypatch):
    monkeypatch.setattr(entity_extractor_module.spacy, "load", lambda _: object())

    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_: None)
            )
        )

    monkeypatch.setattr(entity_extractor_module, "OpenAI", fake_openai, raising=False)

    extractor = entity_extractor_module.EntityExtractor(groq_api_key="key-groq")

    assert extractor.groq_client is not None
    assert captured == {
        "api_key": "key-groq",
        "base_url": "https://api.groq.com/openai/v1",
        "timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS,
    }
