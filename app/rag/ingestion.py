from dataclasses import dataclass
from pathlib import Path

from app.rag.chunker import TextChunk, chunk_text
from app.rag.documents import extract_text
from app.rag.source_metadata import DEFAULT_LIBRARY_ID, SourceMetadata, build_source_metadata


@dataclass(frozen=True)
class IngestedDocument:
    source_id: str
    title: str
    source_type: str
    chunks: list[TextChunk]
    metadata: SourceMetadata
    already_indexed: bool = False


class DocumentIngestionService:
    """Extract and chunk an approved local document before embedding it."""

    def ingest(
        self,
        path: Path,
        *,
        source_id: str,
        chunk_size: int = 1_000,
        library_id: str = DEFAULT_LIBRARY_ID,
        course_id: str | None = None,
        language: str = "es",
    ) -> IngestedDocument:
        text = extract_text(path)
        overlap = min(150, max(1, chunk_size // 5))
        metadata = build_source_metadata(
            path,
            source_id=source_id,
            extracted_text=text,
            library_id=library_id,
            course_id=course_id,
            language=language,
        )
        return IngestedDocument(
            source_id=source_id,
            title=path.stem,
            source_type=path.suffix.removeprefix(".").casefold(),
            chunks=chunk_text(text, source_id=source_id, chunk_size=chunk_size, overlap=overlap),
            metadata=metadata,
        )
