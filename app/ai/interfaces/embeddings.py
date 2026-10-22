from abc import ABC, abstractmethod


class EmbeddingModel(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert text into embedding vectors."""
