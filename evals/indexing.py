"""Safe, isolated indexing of the payload-only retrieval corpus with Ollama."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

PRODUCTION_COLLECTION = "tutor_documents"
EVAL_PREFIX = "tutor_eval_"


@dataclass(frozen=True)
class IndexReport:
    collection: str
    model: str
    point_count: int
    vector_dimension: int
    embedding_ms: int
    qdrant_ms: int
    total_ms: int
    source_counts: dict[str, int]
    memory_rss_bytes: int | None = None
    disk_free_bytes: int | None = None


def validate_destination(collection: str) -> None:
    if collection == PRODUCTION_COLLECTION or not collection.startswith(EVAL_PREFIX):
        raise ValueError(
            f"destino rechazado: {collection!r}; debe comenzar con {EVAL_PREFIX!r} "
            "y nunca ser tutor_documents"
        )


def validate_embeddings(vectors: Sequence[Sequence[float]], expected_dimension: int | None = None) -> int:
    if not vectors:
        raise ValueError("Ollama devolvió cero embeddings.")
    dimension = len(vectors[0])
    if dimension < 1 or (expected_dimension is not None and dimension != expected_dimension):
        raise ValueError("dimensión de embedding inconsistente.")
    for vector in vectors:
        if len(vector) != dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
            raise ValueError("embedding no finito o dimensión inconsistente.")
    return dimension


async def index_records(
    records: Sequence[dict[str, Any]],
    *,
    collection: str,
    model: str,
    embed: Callable[[list[str]], Awaitable[list[list[float]]]],
    qdrant: AsyncQdrantClient,
    recreate: bool = False,
) -> IndexReport:
    validate_destination(collection)
    if not records:
        raise ValueError("el corpus está vacío")
    chunk_ids = [str(record.get("payload", {}).get("chunk_id", "")) for record in records]
    if any(not chunk_id for chunk_id in chunk_ids) or len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("chunk_id ausente o duplicado en el corpus")
    contents = [str(record.get("payload", {}).get("content", "")) for record in records]
    if any(not content.strip() for content in contents):
        raise ValueError("el corpus contiene contenido vacío")

    total_started = time.perf_counter()
    embed_started = time.perf_counter()
    vectors = await embed(contents)
    embedding_ms = round((time.perf_counter() - embed_started) * 1000)
    dimension = validate_embeddings(vectors, expected_dimension=None)
    if len(vectors) != len(records):
        raise ValueError("cantidad de embeddings distinta a cantidad de registros")

    if await qdrant.collection_exists(collection):
        if not recreate:
            raise FileExistsError(f"la colección de evaluación ya existe: {collection}")
        await qdrant.delete_collection(collection)
    await qdrant.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
    )
    qdrant_started = time.perf_counter()
    points = [
        PointStruct(id=str(record["point_id"]), vector=vector, payload=dict(record["payload"]))
        for record, vector in zip(records, vectors, strict=True)
    ]
    await qdrant.upsert(collection_name=collection, points=points, wait=True)
    count = (await qdrant.count(collection_name=collection, exact=True)).count
    if count != len(records):
        raise RuntimeError(f"conteo Qdrant inválido: esperado {len(records)}, obtenido {count}")
    qdrant_ms = round((time.perf_counter() - qdrant_started) * 1000)
    source_counts: dict[str, int] = {}
    for record in records:
        source = str(record["payload"].get("source_id", ""))
        source_counts[source] = source_counts.get(source, 0) + 1
    return IndexReport(
        collection=collection,
        model=model,
        point_count=count,
        vector_dimension=dimension,
        embedding_ms=embedding_ms,
        qdrant_ms=qdrant_ms,
        total_ms=round((time.perf_counter() - total_started) * 1000),
        source_counts=dict(sorted(source_counts.items())),
    )
