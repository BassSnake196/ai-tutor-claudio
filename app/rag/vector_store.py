from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    HasIdCondition,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.rag.source_metadata import SourceRecord, source_record_from_payloads


FilterScalar = str | int | bool
FilterValue = FilterScalar | Sequence[FilterScalar]
PAYLOAD_KEYWORD_INDEXES = (
    "source_id",
    "document_id",
    "library_id",
    "course_id",
    "source_type",
    "status",
    "schema_version",
    "document_hash",
    "content_hash",
)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]


class QdrantVectorStore:
    """Qdrant adapter with payload filtering and source catalog operations."""

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self._client = client or AsyncQdrantClient(url=url)
        self._collection_name = collection_name

    @property
    def collection_name(self) -> str:
        return self._collection_name

    async def ensure_collection(self, vector_size: int) -> None:
        if not await self._client.collection_exists(self._collection_name):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        await self.ensure_payload_indexes()

    async def ensure_payload_indexes(self) -> None:
        if not await self._client.collection_exists(self._collection_name):
            return
        collection = await self._client.get_collection(self._collection_name)
        indexed_fields = set((collection.payload_schema or {}).keys())
        for field_name in PAYLOAD_KEYWORD_INDEXES:
            if field_name in indexed_fields:
                continue
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )

    async def upsert(self, chunks: list[tuple[str, str, list[float], dict[str, Any]]]) -> None:
        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, chunk_id)),
                vector=vector,
                payload={"chunk_id": chunk_id, "content": content, **metadata},
            )
            for chunk_id, content, vector, metadata in chunks
        ]
        if points:
            await self._client.upsert(collection_name=self._collection_name, points=points, wait=True)

    async def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 5,
        include_filters: Mapping[str, FilterValue] | None = None,
        exclude_filters: Mapping[str, FilterValue] | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        results = await self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            query_filter=self.build_filter(include_filters, exclude_filters),
            limit=limit,
            score_threshold=score_threshold,
        )
        return [
            RetrievedChunk(
                chunk_id=str((point.payload or {}).get("chunk_id", point.id)),
                content=str((point.payload or {}).get("content", "")),
                score=point.score,
                metadata={
                    key: value
                    for key, value in (point.payload or {}).items()
                    if key not in {"content", "chunk_id"}
                },
            )
            for point in results.points
        ]

    @staticmethod
    def build_filter(
        include_filters: Mapping[str, FilterValue] | None = None,
        exclude_filters: Mapping[str, FilterValue] | None = None,
    ) -> Filter | None:
        must: list[Any] = []
        must_not: list[Any] = []
        for target, values in ((must, include_filters), (must_not, exclude_filters)):
            for key, value in (values or {}).items():
                normalized = _as_values(value)
                if not normalized:
                    if target is must:
                        must.append(HasIdCondition(has_id=[]))
                    continue
                match = MatchValue(value=normalized[0]) if len(normalized) == 1 else MatchAny(any=normalized)
                target.append(FieldCondition(key=key, match=match))
        if not must and not must_not:
            return None
        return Filter(must=must or None, must_not=must_not or None)

    async def list_sources(
        self,
        *,
        include_filters: Mapping[str, FilterValue] | None = None,
        exclude_filters: Mapping[str, FilterValue] | None = None,
    ) -> list[SourceRecord]:
        payloads = await self._scroll_payloads(
            scroll_filter=self.build_filter(include_filters, exclude_filters)
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for payload in payloads:
            source_id = str(payload.get("source_id", ""))
            if source_id:
                grouped[source_id].append(payload)
        records = [source_record_from_payloads(items) for items in grouped.values()]
        return sorted(records, key=lambda item: (item.title.casefold(), item.source_id))

    async def get_source(self, source_id: str) -> SourceRecord | None:
        payloads = await self._scroll_payloads(
            scroll_filter=self.build_filter({"source_id": source_id})
        )
        return source_record_from_payloads(payloads) if payloads else None

    async def find_sources_by_document_hash(self, document_hash: str) -> list[SourceRecord]:
        return await self.list_sources(include_filters={"document_hash": document_hash})

    async def delete_source(self, source_id: str) -> bool:
        if await self.get_source(source_id) is None:
            return False
        source_filter = self.build_filter({"source_id": source_id})
        assert source_filter is not None
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=FilterSelector(filter=source_filter),
            wait=True,
        )
        return True

    async def _scroll_payloads(self, *, scroll_filter: Filter | None = None) -> list[dict[str, Any]]:
        if not await self._client.collection_exists(self._collection_name):
            return []
        payloads: list[dict[str, Any]] = []
        offset: Any = None
        while True:
            records, next_offset = await self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=scroll_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            payloads.extend(dict(record.payload or {}) for record in records)
            if next_offset is None:
                break
            offset = next_offset
        return payloads


def _as_values(value: FilterValue) -> list[FilterScalar]:
    if isinstance(value, (str, int, bool)):
        return [value]
    return list(value)
