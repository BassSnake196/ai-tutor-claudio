import httpx

from app.ai.interfaces.llm import LLMProviderError, LanguageModel, TextGeneration, TokenUsage


class OllamaLanguageModel(LanguageModel):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._json_mode = json_mode
        self._max_output_tokens = max_output_tokens

    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        result = await self.generate_with_usage(prompt, system_instruction=system_instruction)
        return result.text

    async def generate_with_usage(
        self, prompt: str, *, system_instruction: str | None = None
    ) -> TextGeneration:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        try:
            # Ollama is a loopback-only local service; system proxy settings must not intercept it.
            payload: dict[str, object] = {
                "model": self._model,
                "messages": messages,
                "stream": False,
            }
            if self._json_mode:
                payload["format"] = "json"
            if self._max_output_tokens is not None:
                payload["options"] = {
                    "num_predict": self._max_output_tokens,
                    "temperature": 0,
                }
            async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError("Ollama no está disponible o el modelo no fue descargado.") from exc

        body = response.json()
        content = body.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("Ollama respondió sin contenido válido.")
        prompt_tokens = int(body.get("prompt_eval_count") or 0)
        output_tokens = int(body.get("eval_count") or 0)
        return TextGeneration(
            text=content.strip(),
            model=str(body.get("model") or self._model),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=prompt_tokens + output_tokens,
            ),
        )
