from app.ai.interfaces.llm import LanguageModel, StructuredLanguageModel
from app.ai.interfaces.embeddings import EmbeddingModel
from app.ai.providers.ollama_embeddings import OllamaEmbeddingModel
from app.ai.providers.gemini import GeminiLanguageModel
from app.ai.providers.ollama import OllamaLanguageModel
from app.core.config import Settings


class ModelRegistry:
    """Central place to construct providers from application configuration."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def local_llm(self) -> LanguageModel:
        return OllamaLanguageModel(
            base_url=str(self._settings.ollama_base_url),
            model=self._settings.ollama_model,
            timeout_seconds=self._settings.ollama_timeout_seconds,
        )

    def semantic_critic_llm(self) -> LanguageModel:
        return OllamaLanguageModel(
            base_url=str(self._settings.ollama_base_url),
            model=self._settings.ollama_model,
            timeout_seconds=self._settings.ollama_timeout_seconds,
            json_mode=True,
            max_output_tokens=self._settings.ollama_critic_max_output_tokens,
        )

    def cloud_llm(self) -> StructuredLanguageModel:
        return GeminiLanguageModel(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_model,
            fallback_models=[
                model.strip()
                for model in self._settings.gemini_fallback_models.split(",")
                if model.strip()
            ],
            structured_thinking_budget=self._settings.gemini_structured_thinking_budget,
            structured_max_output_tokens=self._settings.gemini_structured_max_output_tokens,
        )

    def embeddings(self) -> EmbeddingModel:
        return OllamaEmbeddingModel(
            base_url=str(self._settings.ollama_base_url),
            model=self._settings.embedding_model_name,
        )

    @property
    def local_model_name(self) -> str:
        return self._settings.ollama_model
