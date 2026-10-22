"""Isolated Qdrant clone utility and Ollama-backed retrieval adapter."""
from __future__ import annotations
from typing import Any
import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, VectorParams
from .runner import PRODUCTION_COLLECTION, RankedCandidate

async def clone_collection(*, url: str, source: str = PRODUCTION_COLLECTION,
                           destination: str, recreate: bool = False) -> dict[str, Any]:
    if source == PRODUCTION_COLLECTION and destination == PRODUCTION_COLLECTION:
        raise ValueError("source and destination cannot be tutor_documents")
    if destination == PRODUCTION_COLLECTION:
        raise ValueError("refusing productive destination tutor_documents")
    client = AsyncQdrantClient(url=url)
    try:
        if not await client.collection_exists(source): raise ValueError(f"source collection does not exist: {source}")
        if await client.collection_exists(destination):
            if not recreate: raise FileExistsError(f"destination exists; pass recreate=True: {destination}")
            await client.delete_collection(destination)
        info = await client.get_collection(source); params = info.config.params.vectors
        if isinstance(params, dict): raise ValueError("named vectors are not supported by isolated clone")
        await client.create_collection(collection_name=destination, vectors_config=VectorParams(size=params.size, distance=params.distance))
        points, offset = [], None
        while True:
            records, offset = await client.scroll(collection_name=source, offset=offset, limit=256, with_payload=True, with_vectors=True)
            for record in records:
                if not isinstance(record.vector, list) or len(record.vector) != params.size: raise ValueError("source vector dimension mismatch")
                points.append(PointStruct(id=record.id, vector=record.vector, payload=dict(record.payload or {})))
            if offset is None: break
        if points: await client.upsert(collection_name=destination, points=points, wait=True)
        source_count = (await client.count(collection_name=source, exact=True)).count
        dest_count = (await client.count(collection_name=destination, exact=True)).count
        if source_count != dest_count: raise RuntimeError("clone count verification failed")
        return {"source": source, "destination": destination, "count": dest_count, "vector_size": params.size}
    finally: await client.close()

class OllamaQdrantBackend:
    def __init__(self, *, qdrant_url: str, collection: str, ollama_url: str, embedding_model: str, timeout: float = 120) -> None:
        if collection == PRODUCTION_COLLECTION: raise ValueError("evaluation backend cannot use tutor_documents")
        self.client = AsyncQdrantClient(url=qdrant_url); self.collection = collection; self.ollama_url = ollama_url.rstrip("/"); self.embedding_model = embedding_model; self.timeout = timeout

    async def search(self, query: str, *, limit: int, score_threshold: float | None):
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as http:
            response = await http.post(f"{self.ollama_url}/api/embed", json={"model": self.embedding_model, "input": [query]})
            response.raise_for_status(); vectors = response.json().get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1: raise RuntimeError("invalid Ollama embedding response")
        response = await self.client.query_points(collection_name=self.collection, query=vectors[0], limit=limit, score_threshold=score_threshold)
        return [RankedCandidate(str((p.payload or {}).get("chunk_id", p.id)), p.score, {k: v for k, v in (p.payload or {}).items() if k not in {"content", "chunk_id"}}) for p in response.points]

    async def close(self) -> None: await self.client.close()
