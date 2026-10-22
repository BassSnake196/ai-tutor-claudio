import os
from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient

from app.ai.registry import ModelRegistry
from app.core.config import get_settings
from app.rag.service import RagService
from app.rag.vector_store import QdrantVectorStore


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG_TESTS") != "1",
    reason="Requiere Ollama y Qdrant locales.",
)


@pytest.mark.asyncio
async def test_indexes_and_recovers_a_relevant_fragment() -> None:
    settings = get_settings()
    collection_name = f"tutor_documents_live_{uuid4().hex}"
    service = RagService(
        embeddings=ModelRegistry(settings).embeddings(),
        vector_store=QdrantVectorStore(
            url=str(settings.qdrant_url),
            collection_name=collection_name,
        ),
    )
    cleanup = AsyncQdrantClient(url=str(settings.qdrant_url))
    try:
        await service.index_document(Path("tests/fixtures/pedagogy.txt"), source_id="pedagogy-fixture")
        results = await service.search("¿Para qué sirve la evaluación formativa?", limit=3)

        assert results
        assert results[0].metadata["source_id"] == "pedagogy-fixture"
        assert "evaluación formativa" in results[0].content.casefold()
    finally:
        if await cleanup.collection_exists(collection_name):
            await cleanup.delete_collection(collection_name)
        await cleanup.close()
