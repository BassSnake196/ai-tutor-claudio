from dataclasses import dataclass, replace
from pathlib import Path

from app.ai.interfaces.stt import Transcript
from app.ai.interfaces.embeddings import EmbeddingModel
from app.rag.ingestion import DocumentIngestionService, IngestedDocument
from app.rag.chunker import TextChunk, chunk_text
from app.rag.source_metadata import (
    DEFAULT_LIBRARY_ID,
    SourceMetadata,
    SourceRecord,
    content_hash,
    document_id,
    utc_now_iso,
)
from app.rag.vector_store import FilterValue, QdrantVectorStore, RetrievedChunk
from app.rag.youtube_ingestion import IngestedYouTubeTranscript, TimedTextChunk
from app.schemas.source_resolution import EvidenceBundle, ResolutionStage


@dataclass(frozen=True)
class IndexedExternalSource:
    source_id: str
    title: str
    source_type: str
    chunk_count: int
    already_indexed: bool = False


class DuplicateDocumentError(ValueError):
    def __init__(self, source_ids: list[str]) -> None:
        self.source_ids = source_ids
        super().__init__(f"El mismo contenido ya está indexado en: {', '.join(source_ids)}.")


class SourceIdConflictError(ValueError):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"source_id '{source_id}' ya existe con contenido diferente.")


class RagService:
    def __init__(self, *, embeddings: EmbeddingModel, vector_store: QdrantVectorStore) -> None:
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._ingestion = DocumentIngestionService()

    async def index_document(
        self,
        path: Path,
        *,
        source_id: str,
        library_id: str = DEFAULT_LIBRARY_ID,
        course_id: str | None = None,
        language: str = "es",
    ) -> IngestedDocument:
        document = self._ingestion.ingest(
            path,
            source_id=source_id,
            library_id=library_id,
            course_id=course_id,
            language=language,
        )
        if not document.chunks:
            raise ValueError("El documento no contiene texto indexable.")

        current_source = await self._vector_store.get_source(source_id)
        if current_source:
            if current_source.document_hash == document.metadata.document_hash:
                return replace(document, already_indexed=True)
            raise SourceIdConflictError(source_id)

        duplicates = await self._vector_store.find_sources_by_document_hash(
            document.metadata.document_hash
        )
        if duplicates:
            raise DuplicateDocumentError([item.source_id for item in duplicates])

        vectors = await self._embeddings.embed([chunk.content for chunk in document.chunks])
        await self._vector_store.ensure_collection(len(vectors[0]))
        await self._vector_store.upsert(
            [
                (
                    chunk.chunk_id,
                    chunk.content,
                    vector,
                    document.metadata.chunk_payload(
                        chunk_content=chunk.content,
                        chunk_index=chunk.index,
                    ),
                )
                for chunk, vector in zip(document.chunks, vectors, strict=True)
            ]
        )
        return document

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        include_filters: dict[str, FilterValue] | None = None,
        exclude_filters: dict[str, FilterValue] | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        vector = (await self._embeddings.embed([query]))[0]
        return await self._vector_store.search(
            vector,
            limit=limit,
            include_filters=include_filters,
            exclude_filters=exclude_filters,
            score_threshold=score_threshold,
        )

    async def index_external_text(
        self,
        content: str,
        *,
        source_id: str,
        title: str,
        source_type: str,
        url: str,
        library_id: str = DEFAULT_LIBRARY_ID,
        course_id: str | None = None,
        language: str = "es",
        author: str | None = None,
    ) -> IndexedExternalSource:
        chunks = chunk_text(content, source_id=source_id)
        if not chunks:
            raise ValueError("La fuente externa no contiene texto indexable.")
        digest = content_hash(content)
        metadata = SourceMetadata(
            source_id=source_id,
            document_id=document_id(source_id=source_id, document_hash=digest),
            library_id=library_id,
            course_id=course_id,
            title=title,
            source_type=source_type,
            language=language,
            document_hash=digest,
            ingested_at=utc_now_iso(),
            url=url,
            author=author,
        )
        already_indexed = await self._index_external_chunks(metadata, chunks)
        return IndexedExternalSource(
            source_id=source_id,
            title=title,
            source_type=source_type,
            chunk_count=len(chunks),
            already_indexed=already_indexed,
        )

    async def index_youtube_transcript(
        self,
        document: IngestedYouTubeTranscript,
        *,
        source_id: str,
        library_id: str = DEFAULT_LIBRARY_ID,
        course_id: str | None = None,
        language: str = "es",
    ) -> IndexedExternalSource:
        digest = content_hash(document.transcript.text)
        metadata = SourceMetadata(
            source_id=source_id,
            document_id=document_id(source_id=source_id, document_hash=digest),
            library_id=library_id,
            course_id=course_id,
            title=document.asset.title,
            source_type="youtube",
            language=document.transcript.language or language,
            document_hash=digest,
            ingested_at=utc_now_iso(),
            storage_path=(
                str(document.asset.audio_path.resolve()) if document.asset.audio_path else None
            ),
            original_filename=(document.asset.audio_path.name if document.asset.audio_path else None),
            url=document.asset.canonical_url,
            author=document.asset.channel,
            duration_seconds=document.asset.duration_seconds,
        )
        already_indexed = await self._index_external_chunks(metadata, list(document.chunks))
        return IndexedExternalSource(
            source_id=source_id,
            title=document.asset.title,
            source_type="youtube",
            chunk_count=len(document.chunks),
            already_indexed=already_indexed,
        )

    async def index_audio_transcript(
        self,
        transcript: Transcript,
        *,
        source_id: str,
        title: str,
        storage_path: Path,
        library_id: str = DEFAULT_LIBRARY_ID,
        course_id: str | None = None,
        language: str = "es",
    ) -> IndexedExternalSource:
        chunks = list(chunk_transcript(transcript, source_id=source_id))
        if not chunks:
            raise ValueError("La transcripción no contiene texto indexable.")
        digest = content_hash(transcript.text)
        metadata = SourceMetadata(
            source_id=source_id,
            document_id=document_id(source_id=source_id, document_hash=digest),
            library_id=library_id,
            course_id=course_id,
            title=title,
            source_type="transcript",
            language=transcript.language or language,
            document_hash=digest,
            ingested_at=utc_now_iso(),
            storage_path=str(storage_path.resolve()),
            original_filename=storage_path.name,
            duration_seconds=transcript.duration_seconds,
        )
        already_indexed = await self._index_external_chunks(metadata, chunks)
        return IndexedExternalSource(
            source_id=source_id,
            title=title,
            source_type="transcript",
            chunk_count=len(chunks),
            already_indexed=already_indexed,
        )

    async def _index_external_chunks(
        self,
        metadata: SourceMetadata,
        chunks: list[TextChunk] | list[TimedTextChunk],
    ) -> bool:
        current_source = await self._vector_store.get_source(metadata.source_id)
        if current_source:
            if current_source.document_hash == metadata.document_hash:
                return True
            raise SourceIdConflictError(metadata.source_id)
        duplicates = await self._vector_store.find_sources_by_document_hash(metadata.document_hash)
        if duplicates:
            raise DuplicateDocumentError([item.source_id for item in duplicates])

        vectors = await self._embeddings.embed([chunk.content for chunk in chunks])
        await self._vector_store.ensure_collection(len(vectors[0]))
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            payload = metadata.chunk_payload(
                chunk_content=chunk.content,
                chunk_index=chunk.index,
            )
            if isinstance(chunk, TimedTextChunk):
                payload["timestamp_start"] = chunk.timestamp_start
                payload["timestamp_end"] = chunk.timestamp_end
            points.append((chunk.chunk_id, chunk.content, vector, payload))
        await self._vector_store.upsert(points)
        return False

    async def cache_external_evidence(
        self,
        evidence: EvidenceBundle,
        *,
        library_id: str,
        course_id: str | None = None,
    ) -> tuple[int, list[str]]:
        """Persist accepted live evidence so later runs can resolve it locally."""
        grouped: dict[str, list] = {}
        for chunk in evidence.chunks:
            if chunk.stage is ResolutionStage.EXTERNAL:
                grouped.setdefault(chunk.metadata.source_id, []).append(chunk)

        cached = 0
        warnings: list[str] = []
        for source_id, source_chunks in grouped.items():
            combined = "\n".join(dict.fromkeys(chunk.content for chunk in source_chunks))
            digest = content_hash(combined)
            first = source_chunks[0].metadata
            metadata = SourceMetadata(
                source_id=source_id,
                document_id=document_id(source_id=source_id, document_hash=digest),
                library_id=library_id,
                course_id=course_id,
                title=first.title or source_id,
                source_type=str(first.source_type.value),
                language=first.language,
                document_hash=digest,
                ingested_at=utc_now_iso(),
                url=str(first.url) if first.url else None,
                author=first.author,
                duration_seconds=first.duration_seconds,
            )
            indexable: list[TextChunk] | list[TimedTextChunk]
            if all(
                chunk.metadata.timestamp_start is not None
                and chunk.metadata.timestamp_end is not None
                for chunk in source_chunks
            ):
                indexable = [
                    TimedTextChunk(
                        chunk_id=chunk.chunk_id,
                        content=chunk.content,
                        index=index,
                        timestamp_start=float(chunk.metadata.timestamp_start),
                        timestamp_end=float(chunk.metadata.timestamp_end),
                    )
                    for index, chunk in enumerate(source_chunks)
                ]
            else:
                indexable = [
                    TextChunk(chunk_id=chunk.chunk_id, content=chunk.content, index=index)
                    for index, chunk in enumerate(source_chunks)
                ]
            try:
                already_indexed = await self._index_external_chunks(metadata, indexable)
            except (DuplicateDocumentError, SourceIdConflictError) as exc:
                warnings.append(f"No se almacenó la fuente externa {source_id}: {exc}")
            else:
                if not already_indexed:
                    cached += 1
        return cached, warnings

    async def list_sources(
        self,
        *,
        library_id: str | None = None,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[SourceRecord]:
        filters: dict[str, FilterValue] = {}
        if library_id:
            filters["library_id"] = library_id
        if course_id:
            filters["course_id"] = course_id
        if status:
            filters["status"] = status
        return await self._vector_store.list_sources(include_filters=filters)

    async def get_source(self, source_id: str) -> SourceRecord | None:
        return await self._vector_store.get_source(source_id)

    async def delete_source(self, source_id: str) -> bool:
        return await self._vector_store.delete_source(source_id)
