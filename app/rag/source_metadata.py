from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


PAYLOAD_SCHEMA_VERSION = "2"
DEFAULT_LIBRARY_ID = "default"
ACTIVE_STATUS = "ACTIVE"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def content_hash(content: str) -> str:
    """Return a stable digest for normalized text content."""
    normalized = " ".join(content.split())
    return sha256(normalized.encode("utf-8")).hexdigest()


def document_id(*, source_id: str, document_hash: str) -> str:
    """Identify a concrete version of a logical source deterministically."""
    return sha256(f"{source_id}:{document_hash}".encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    document_id: str
    library_id: str
    course_id: str | None
    title: str
    source_type: str
    language: str
    document_hash: str
    ingested_at: str
    status: str = ACTIVE_STATUS
    schema_version: str = PAYLOAD_SCHEMA_VERSION
    storage_path: str | None = None
    original_filename: str | None = None
    author: str | None = None
    duration_seconds: float | None = None
    page_number: int | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    url: str | None = None

    def chunk_payload(self, *, chunk_content: str, chunk_index: int) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "chunk_index": chunk_index,
                "content_hash": content_hash(chunk_content),
            }
        )
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    document_id: str
    library_id: str
    course_id: str | None
    title: str
    source_type: str
    language: str
    document_hash: str
    ingested_at: str
    status: str
    schema_version: str
    chunk_count: int
    storage_paths: tuple[str, ...] = ()
    author: str | None = None
    duration_seconds: float | None = None
    url: str | None = None

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("storage_paths", None)
        return data


def build_source_metadata(
    path: Path,
    *,
    source_id: str,
    extracted_text: str,
    library_id: str = DEFAULT_LIBRARY_ID,
    course_id: str | None = None,
    language: str = "es",
) -> SourceMetadata:
    digest = content_hash(extracted_text)
    return SourceMetadata(
        source_id=source_id,
        document_id=document_id(source_id=source_id, document_hash=digest),
        library_id=library_id,
        course_id=course_id,
        title=path.stem,
        source_type=path.suffix.removeprefix(".").casefold(),
        language=language,
        document_hash=digest,
        ingested_at=utc_now_iso(),
        storage_path=str(path.resolve()),
        original_filename=path.name,
    )


def source_record_from_payloads(payloads: list[dict[str, Any]]) -> SourceRecord:
    if not payloads:
        raise ValueError("Se requiere al menos un payload para construir la fuente.")
    first = payloads[0]
    storage_paths = tuple(
        sorted({str(payload["storage_path"]) for payload in payloads if payload.get("storage_path")})
    )
    return SourceRecord(
        source_id=str(first.get("source_id", "")),
        document_id=str(first.get("document_id", first.get("source_id", ""))),
        library_id=str(first.get("library_id", DEFAULT_LIBRARY_ID)),
        course_id=str(first["course_id"]) if first.get("course_id") is not None else None,
        title=str(first.get("title", first.get("source_id", ""))),
        source_type=str(first.get("source_type", "unknown")),
        language=str(first.get("language", "und")),
        document_hash=str(first.get("document_hash", "")),
        ingested_at=str(first.get("ingested_at", "")),
        status=str(first.get("status", ACTIVE_STATUS)),
        schema_version=str(first.get("schema_version", "1")),
        chunk_count=len(payloads),
        storage_paths=storage_paths,
        author=str(first["author"]) if first.get("author") else None,
        duration_seconds=(
            float(first["duration_seconds"])
            if first.get("duration_seconds") is not None
            else None
        ),
        url=str(first["url"]) if first.get("url") else None,
    )
