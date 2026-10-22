"""Shared source, citation and grounding contracts.

These models intentionally live outside ``responses.py`` so curriculum schemas and
API response envelopes can depend on the same types without circular imports.
``responses.py`` re-exports ``Citation`` and ``GroundingStatus`` for compatibility.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceType(StrEnum):
    TXT = "txt"
    PDF = "pdf"
    DOCX = "docx"
    WEB = "web"
    YOUTUBE = "youtube"
    TRANSCRIPT = "transcript"
    OTHER = "other"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    DELETED = "DELETED"


class GroundingStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTORY_SOURCES = "CONTRADICTORY_SOURCES"


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=200)
    fragment_reference: str = Field(min_length=1, max_length=500)
    timestamp_start: float | None = Field(default=None, ge=0)
    timestamp_end: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_timestamp_range(self) -> "Citation":
        if (
            self.timestamp_start is not None
            and self.timestamp_end is not None
            and self.timestamp_end < self.timestamp_start
        ):
            raise ValueError("timestamp_end must be greater than or equal to timestamp_start")
        return self


class SourceMetadata(BaseModel):
    """Normalized, user-readable metadata associated with a Qdrant chunk."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="2", min_length=1, max_length=20)
    source_id: str = Field(min_length=1, max_length=200)
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    library_id: str = Field(default="default", min_length=1, max_length=100)
    course_id: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    source_type: SourceType = SourceType.OTHER
    language: str = Field(default="es", min_length=2, max_length=20)
    chunk_index: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)
    timestamp_start: float | None = Field(default=None, ge=0)
    timestamp_end: float | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=2_000)
    content_hash: str | None = Field(default=None, min_length=16, max_length=128)
    document_hash: str | None = Field(default=None, min_length=16, max_length=128)
    ingested_at: datetime | None = None
    original_filename: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    duration_seconds: float | None = Field(default=None, ge=0)
    storage_path: str | None = Field(default=None, max_length=2_000, exclude=True)
    status: SourceStatus = SourceStatus.ACTIVE

    @model_validator(mode="after")
    def validate_timestamp_range(self) -> "SourceMetadata":
        if (
            self.timestamp_start is not None
            and self.timestamp_end is not None
            and self.timestamp_end < self.timestamp_start
        ):
            raise ValueError("timestamp_end must be greater than or equal to timestamp_start")
        return self
