from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.service import DuplicateDocumentError, RagService
from app.rag.source_metadata import build_source_metadata, content_hash
from app.rag.vector_store import QdrantVectorStore
from scripts.migrate_qdrant_payload_v2 import migrate_payload_v2


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0, float(index), 0.0] for index, _ in enumerate(texts)]


def test_source_metadata_v2_is_stable_and_traceable(tmp_path: Path) -> None:
    path = tmp_path / "algebra.txt"
    path.write_text("  Ecuaciones   lineales  ", encoding="utf-8")

    metadata = build_source_metadata(
        path,
        source_id="algebra-1",
        extracted_text=path.read_text(encoding="utf-8"),
        library_id="escuela",
        course_id="matematicas",
    )
    payload = metadata.chunk_payload(chunk_content="Ecuaciones lineales", chunk_index=0)

    assert payload["schema_version"] == "2"
    assert payload["library_id"] == "escuela"
    assert payload["course_id"] == "matematicas"
    assert payload["document_hash"] == content_hash("Ecuaciones lineales")
    assert payload["content_hash"] == content_hash("Ecuaciones lineales")
    assert payload["status"] == "ACTIVE"


def test_filters_use_and_between_fields_and_or_within_a_field() -> None:
    query_filter = QdrantVectorStore.build_filter(
        {"source_id": ["a", "b"], "library_id": "default"},
        {"status": "ARCHIVED"},
    )

    assert query_filter is not None
    assert len(query_filter.must or []) == 2
    assert len(query_filter.must_not or []) == 1


@pytest.mark.asyncio
async def test_vector_store_filters_catalog_and_exact_source_deletion() -> None:
    client = AsyncQdrantClient(":memory:")
    store = QdrantVectorStore(url="http://unused", collection_name="payload-v2", client=client)
    try:
        await store.ensure_collection(3)
        await store.upsert(
            [
                (
                    "source-a:1",
                    "contenido a",
                    [1.0, 0.0, 0.0],
                    _payload("source-a", "doc-a", "hash-a", 0),
                ),
                (
                    "source-b:1",
                    "contenido b",
                    [0.9, 0.1, 0.0],
                    _payload("source-b", "doc-b", "hash-b", 0),
                ),
            ]
        )

        selected = await store.search(
            [1.0, 0.0, 0.0],
            include_filters={"library_id": "default", "source_id": ["source-a", "source-b"]},
            exclude_filters={"source_id": ["source-b"]},
        )
        sources = await store.list_sources(include_filters={"library_id": "default"})
        detail = await store.get_source("source-a")
        deleted = await store.delete_source("source-a")

        assert [item.metadata["source_id"] for item in selected] == ["source-a"]
        assert [item.source_id for item in sources] == ["source-a", "source-b"]
        assert detail is not None and detail.chunk_count == 1
        assert deleted is True
        assert await store.get_source("source-a") is None
        assert await store.get_source("source-b") is not None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ingestion_is_idempotent_and_rejects_duplicate_content(tmp_path: Path) -> None:
    client = AsyncQdrantClient(":memory:")
    store = QdrantVectorStore(url="http://unused", collection_name="dedupe", client=client)
    embeddings = FakeEmbeddings()
    service = RagService(embeddings=embeddings, vector_store=store)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("Contenido didáctico único.", encoding="utf-8")
    second.write_text("Contenido didáctico único.", encoding="utf-8")
    try:
        indexed = await service.index_document(first, source_id="source-a")
        repeated = await service.index_document(first, source_id="source-a")

        assert indexed.already_indexed is False
        assert repeated.already_indexed is True
        assert embeddings.calls == 1
        with pytest.raises(DuplicateDocumentError):
            await service.index_document(second, source_id="source-b")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_payload_migration_is_non_destructive_and_idempotent() -> None:
    client = AsyncQdrantClient(":memory:")
    collection = "legacy"
    try:
        await client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=3, distance=Distance.COSINE),
        )
        await client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=1,
                    vector=[1.0, 0.0, 0.0],
                    payload={
                        "chunk_id": "legacy-source:abc",
                        "content": "Texto heredado",
                        "source_id": "legacy-source",
                        "title": "Fuente heredada",
                        "source_type": "txt",
                        "chunk_index": 0,
                    },
                )
            ],
            wait=True,
        )

        first = await migrate_payload_v2(
            client,
            collection_name=collection,
            create_snapshot=False,
        )
        second = await migrate_payload_v2(
            client,
            collection_name=collection,
            create_snapshot=False,
        )
        records, _ = await client.scroll(collection_name=collection, limit=10, with_payload=True)

        assert first.points_before == first.points_after == 1
        assert first.updated_points == 1
        assert second.points_before == second.points_after == 1
        assert second.updated_points == 0
        assert records[0].payload["schema_version"] == "2"
        assert records[0].payload["library_id"] == "default"
        assert records[0].payload["content_hash"] == content_hash("Texto heredado")
    finally:
        await client.close()


def _payload(
    source_id: str,
    document_id: str,
    document_hash: str,
    chunk_index: int,
) -> dict[str, object]:
    return {
        "schema_version": "2",
        "source_id": source_id,
        "document_id": document_id,
        "library_id": "default",
        "title": source_id,
        "source_type": "txt",
        "language": "es",
        "chunk_index": chunk_index,
        "content_hash": f"chunk-{source_id}-{chunk_index}",
        "document_hash": document_hash,
        "ingested_at": "2026-08-27T00:00:00+00:00",
        "status": "ACTIVE",
    }
