import httpx

from app.ai.interfaces.embeddings import EmbeddingModel


class OllamaEmbeddingModel(EmbeddingModel):
    """Local embeddings through Ollama's loopback API."""

    def __init__(self, *, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama devolvió una cantidad inválida de embeddings.")
        return embeddings
