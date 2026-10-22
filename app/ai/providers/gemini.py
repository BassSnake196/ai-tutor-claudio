import asyncio
import json
import time
from collections.abc import Sequence
from pydantic import ValidationError
from app.ai.interfaces.llm import LLMProviderError, ModelT, StructuredGeneration, StructuredLanguageModel, TextGeneration, TokenUsage

class GeminiLanguageModel(StructuredLanguageModel):
    def __init__(self, *, api_key: str | None, model: str, fallback_models: Sequence[str] = (), structured_thinking_budget: int = 1_024, structured_max_output_tokens: int = 8_192) -> None:
        if structured_thinking_budget < 0: raise ValueError("structured_thinking_budget no puede ser negativo.")
        if structured_max_output_tokens < 1: raise ValueError("structured_max_output_tokens debe ser positivo.")
        self._api_key, self._models = api_key, tuple(dict.fromkeys((model, *fallback_models)))
        self._structured_thinking_budget, self._structured_max_output_tokens = structured_thinking_budget, structured_max_output_tokens
        self.attempt_log: list[dict[str, object]] = []

    def drain_attempt_log(self, *, limit: int | None = None) -> list[dict[str, object]]:
        events = list(self.attempt_log if limit is None else self.attempt_log[:limit]); del self.attempt_log[:len(events)]; return events

    def _event(self, *, model: str, kind: str, status: str, started: float, fallback: bool, repair: bool, usage: TokenUsage = TokenUsage(), error_type: str | None = None) -> None:
        event: dict[str, object] = {"model": model, "kind": kind, "status": status, "latency_ms": (time.perf_counter() - started) * 1000, "fallback": fallback, "repair": repair, "prompt_tokens": usage.prompt_tokens, "output_tokens": usage.output_tokens, "total_tokens": usage.total_tokens}
        if error_type: event["error_type"] = error_type
        self.attempt_log.append(event); del self.attempt_log[:-1000]

    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        return (await self.generate_with_usage(prompt, system_instruction=system_instruction)).text

    async def generate_with_usage(self, prompt: str, *, system_instruction: str | None = None) -> TextGeneration:
        client, errors, types = self._client(); last_error: Exception | None = None
        for index, model in enumerate(self._models):
            started = time.perf_counter()
            try:
                kwargs = {"model": model, "contents": prompt}
                if system_instruction: kwargs["config"] = types.GenerateContentConfig(system_instruction=system_instruction)
                response = await asyncio.to_thread(client.models.generate_content, **kwargs); text = getattr(response, "text", None); usage = self._extract_usage(response)
                if isinstance(text, str) and text.strip():
                    self._event(model=model, kind="text", status="success", started=started, fallback=index > 0, repair=False, usage=usage); return TextGeneration(text=text.strip(), model=model, usage=usage)
                last_error = ValueError("empty response"); self._event(model=model, kind="text", status="invalid", started=started, fallback=index > 0, repair=False, usage=usage, error_type="ValueError")
            except errors.APIError as exc:
                last_error = exc; self._event(model=model, kind="text", status="error", started=started, fallback=index > 0, repair=False, error_type=type(exc).__name__)
                if exc.code in {401, 403}: raise LLMProviderError("Gemini rechazó la API key o sus permisos.") from exc
                if exc.code == 429: raise LLMProviderError("Gemini alcanzó temporalmente el límite de cuota.") from exc
                if exc.code not in {404, 500, 502, 503, 504}: raise LLMProviderError(f"Gemini rechazó la solicitud (código {exc.code}).") from exc
            except Exception as exc:
                last_error = exc; self._event(model=model, kind="text", status="error", started=started, fallback=index > 0, repair=False, error_type=type(exc).__name__)
        raise LLMProviderError(f"Gemini no está disponible temporalmente después de probar: {', '.join(self._models)}.") from last_error

    async def generate_structured(self, prompt: str, *, response_schema: type[ModelT], system_instruction: str | None = None, repair_attempts: int = 1) -> StructuredGeneration[ModelT]:
        if not self._api_key: raise LLMProviderError("GEMINI_API_KEY no está configurada.")
        if repair_attempts not in (0, 1): raise ValueError("repair_attempts debe ser 0 o 1 para controlar costo y latencia.")
        client, errors, types = self._client(); config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=response_schema.model_json_schema(), thinking_config=types.ThinkingConfig(thinking_budget=self._structured_thinking_budget, include_thoughts=False), max_output_tokens=self._structured_max_output_tokens, system_instruction=system_instruction); last_error: Exception | None = None
        for model_index, model in enumerate(self._models):
            contents = prompt
            for attempt in range(repair_attempts + 1):
                started = time.perf_counter()
                try:
                    response = await asyncio.to_thread(client.models.generate_content, model=model, contents=contents, config=config); usage = self._extract_usage(response)
                    try: value = self._parse_structured_response(response, response_schema)
                    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                        last_error = exc; self._event(model=model, kind="structured", status="invalid", started=started, fallback=model_index > 0, repair=attempt > 0, usage=usage, error_type=type(exc).__name__)
                        if attempt >= repair_attempts: break
                        contents = f"{prompt}\n\nLa salida anterior no cumplió el esquema. Corrige únicamente la estructura JSON; no agregues hechos ni fuentes.\nErrores de validación: {exc}\nSalida inválida: {str(getattr(response, 'text', ''))[:8000]}"; continue
                    self._event(model=model, kind="structured", status="success", started=started, fallback=model_index > 0, repair=attempt > 0, usage=usage); return StructuredGeneration(value=value, model=model, usage=usage)
                except errors.APIError as exc:
                    last_error = exc; self._event(model=model, kind="structured", status="error", started=started, fallback=model_index > 0, repair=attempt > 0, error_type=type(exc).__name__)
                    if exc.code in {401, 403}: raise LLMProviderError("Gemini rechazó la API key o sus permisos.") from exc
                    if exc.code == 429: raise LLMProviderError("Gemini alcanzó temporalmente el límite de cuota.") from exc
                    break
                except Exception as exc:
                    last_error = exc; self._event(model=model, kind="structured", status="error", started=started, fallback=model_index > 0, repair=attempt > 0, error_type=type(exc).__name__); break
        raise LLMProviderError(f"Gemini no produjo una salida estructurada válida después de probar: {', '.join(self._models)}.") from last_error

    def _client(self):
        if not self._api_key: raise LLMProviderError("GEMINI_API_KEY no está configurada.")
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc: raise LLMProviderError("El SDK de Gemini no está instalado.") from exc
        return genai.Client(api_key=self._api_key, http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=2, initial_delay=.5, max_delay=2.0, http_status_codes=[408,429,500,502,503,504]))), errors, types

    @staticmethod
    def _parse_structured_response(response: object, response_schema: type[ModelT]) -> ModelT:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_schema): return parsed
        if parsed is not None: return response_schema.model_validate(parsed)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip(): raise ValueError("Gemini respondió sin contenido JSON.")
        return response_schema.model_validate_json(text)

    @staticmethod
    def _extract_usage(response: object) -> TokenUsage:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None: return TokenUsage()
        prompt = int(getattr(metadata, "prompt_token_count", 0) or 0); output = int(getattr(metadata, "candidates_token_count", 0) or 0); total = int(getattr(metadata, "total_token_count", prompt + output) or prompt + output)
        return TokenUsage(prompt_tokens=prompt, output_tokens=output, other_tokens=max(0, total - prompt - output), total_tokens=total)
