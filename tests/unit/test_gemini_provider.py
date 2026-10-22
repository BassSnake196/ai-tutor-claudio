from types import SimpleNamespace

import pytest
from google import genai
from google.genai import errors
from pydantic import BaseModel, ConfigDict

from app.ai.interfaces.llm import LLMProviderError
from app.ai.providers.gemini import GeminiLanguageModel


class StructuredFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


@pytest.mark.asyncio
async def test_uses_fallback_after_temporary_model_failure(monkeypatch) -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, contents: str):
            calls.append(model)
            if model == "primary":
                raise errors.ServerError(
                    503,
                    {"error": {"code": 503, "status": "UNAVAILABLE"}},
                )
            return SimpleNamespace(text="Respuesta alternativa")

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )

    provider = GeminiLanguageModel(
        api_key="test-key",
        model="primary",
        fallback_models=["fallback"],
    )

    result = await provider.generate("Hola")

    assert result == "Respuesta alternativa"
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_reports_quota_error_without_trying_fallback(monkeypatch) -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, contents: str):
            calls.append(model)
            raise errors.ClientError(
                429,
                {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}},
            )

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )

    provider = GeminiLanguageModel(
        api_key="test-key",
        model="primary",
        fallback_models=["fallback"],
    )

    with pytest.raises(LLMProviderError, match="límite de cuota"):
        await provider.generate("Hola")

    assert calls == ["primary"]


@pytest.mark.asyncio
async def test_generates_and_validates_structured_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config):
            captured["config"] = config
            return SimpleNamespace(
                parsed={"title": "Temario válido"},
                text=None,
                usage_metadata=SimpleNamespace(
                    prompt_token_count=120,
                    candidates_token_count=45,
                    total_token_count=165,
                ),
            )

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )
    provider = GeminiLanguageModel(api_key="test-key", model="structured-model")

    result = await provider.generate_structured(
        "Genera un temario",
        response_schema=StructuredFixture,
        system_instruction="Reglas del sistema",
    )

    assert result.value == StructuredFixture(title="Temario válido")
    assert result.model == "structured-model"
    assert result.usage.total_tokens == 165
    config = captured["config"]
    assert config.thinking_config.thinking_budget == 1_024  # type: ignore[union-attr]
    assert config.max_output_tokens == 8_192  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_repairs_invalid_structured_output_once(monkeypatch) -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config):
            calls.append(contents)
            if len(calls) == 1:
                return SimpleNamespace(parsed=None, text='{"unknown": true}')
            return SimpleNamespace(parsed=None, text='{"title": "Reparado"}')

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )
    provider = GeminiLanguageModel(api_key="test-key", model="structured-model")

    result = await provider.generate_structured(
        "Genera un temario",
        response_schema=StructuredFixture,
        system_instruction="Reglas del sistema",
    )

    assert result.value.title == "Reparado"
    assert len(calls) == 2
    assert "Errores de validación" in calls[1]
    assert all("Reglas del sistema" not in content for content in calls)


@pytest.mark.asyncio
async def test_structured_output_falls_back_after_transport_timeout(monkeypatch) -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config):
            calls.append(model)
            if model == "primary":
                raise TimeoutError("transport timeout")
            return SimpleNamespace(parsed={"title": "Fallback"}, text=None)

    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=FakeModels()),
    )
    provider = GeminiLanguageModel(
        api_key="test-key",
        model="primary",
        fallback_models=["fallback"],
    )

    result = await provider.generate_structured(
        "Genera un temario",
        response_schema=StructuredFixture,
    )

    assert result.model == "fallback"
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_system_instruction_is_separate_from_user_contents(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, *, model: str, contents: str, config):
            captured["contents"] = contents
            captured["system"] = config.system_instruction
            return SimpleNamespace(text="ok", usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=2, total_token_count=5))

    monkeypatch.setattr(genai, "Client", lambda **_kwargs: SimpleNamespace(models=FakeModels()))
    provider = GeminiLanguageModel(api_key="test-key", model="m")
    result = await provider.generate_with_usage("user", system_instruction="system")
    assert result.text == "ok" and result.usage.total_tokens == 5
    assert captured == {"contents": "user", "system": "system"}


@pytest.mark.asyncio
async def test_concurrent_usage_calls_keep_results_and_emit_terminal_events(monkeypatch) -> None:
    class FakeModels:
        def generate_content(self, *, model: str, contents: str):
            return SimpleNamespace(text=f"reply-{contents}", usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=2, total_token_count=3))

    monkeypatch.setattr(genai, "Client", lambda **_kwargs: SimpleNamespace(models=FakeModels()))
    provider = GeminiLanguageModel(api_key="test-key", model="m")
    results = await __import__("asyncio").gather(provider.generate_with_usage("a"), provider.generate_with_usage("b"))
    assert [item.text for item in results] == ["reply-a", "reply-b"]
    assert len(provider.attempt_log) == 2
    assert all(event["status"] == "success" and "latency_ms" in event for event in provider.attempt_log)
    assert provider.drain_attempt_log(limit=1)[0]["total_tokens"] == 3
    assert len(provider.attempt_log) == 1
