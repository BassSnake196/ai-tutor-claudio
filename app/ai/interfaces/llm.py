from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMProviderError(RuntimeError):
    """A configured language-model provider could not fulfill a request."""


class LanguageModel(ABC):
    @abstractmethod
    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        """Generate text without exposing provider-specific SDK details."""


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    other_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class TextGeneration:
    text: str
    model: str
    usage: TokenUsage = TokenUsage()


@dataclass(frozen=True)
class StructuredGeneration(Generic[ModelT]):
    value: ModelT
    model: str
    usage: TokenUsage = TokenUsage()


class StructuredLanguageModel(LanguageModel, ABC):
    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        *,
        response_schema: type[ModelT],
        system_instruction: str | None = None,
        repair_attempts: int = 1,
    ) -> StructuredGeneration[ModelT]:
        """Generate and validate a provider-independent Pydantic object."""
