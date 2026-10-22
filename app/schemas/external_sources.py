"""Strict contracts for asynchronous web, YouTube and audio ingestion."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class ExternalSourceType(StrEnum):
    WEB = "WEB"
    YOUTUBE = "YOUTUBE"
    FILE_AUDIO = "FILE_AUDIO"


class IngestionJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _strip_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


NonEmptyText = Annotated[str, AfterValidator(_strip_non_empty)]
SafeIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"),
]
SafeFileReference = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$"),
]


class ExternalIngestionRequest(BaseModel):
    """Describes a source without accepting arbitrary local filesystem paths."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "source_type": "WEB",
                    "source_id": "didactica-algebra-web",
                    "url": "https://example.edu/algebra/didactica",
                    "library_id": "default",
                    "course_id": "matematicas-secundaria",
                    "language": "es",
                },
                {
                    "source_type": "YOUTUBE",
                    "source_id": "video-ecuaciones-01",
                    "url": "https://www.youtube.com/watch?v=abcdefghijk",
                    "library_id": "default",
                    "language": "es-MX",
                },
                {
                    "source_type": "FILE_AUDIO",
                    "source_id": "clase-grabada-01",
                    "file_reference": "upload-audio-01.mp3",
                    "library_id": "default",
                    "language": "es",
                },
            ]
        },
    )

    source_type: ExternalSourceType
    source_id: SafeIdentifier
    url: AnyHttpUrl | None = None
    file_reference: SafeFileReference | None = None
    library_id: SafeIdentifier = "default"
    course_id: SafeIdentifier | None = None
    language: str = Field(default="es", pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    title: NonEmptyText | None = Field(default=None, max_length=500)
    start_time_seconds: float | None = Field(default=None, ge=0)
    end_time_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_locator_and_media_range(self) -> "ExternalIngestionRequest":
        if self.source_type in {ExternalSourceType.WEB, ExternalSourceType.YOUTUBE}:
            if self.url is None:
                raise ValueError(f"{self.source_type.value} requires url")
            if self.file_reference is not None:
                raise ValueError(f"{self.source_type.value} does not accept file_reference")
        elif self.source_type is ExternalSourceType.FILE_AUDIO:
            if self.file_reference is None:
                raise ValueError("FILE_AUDIO requires file_reference")
            if self.url is not None:
                raise ValueError("FILE_AUDIO does not accept url")

        if self.source_type is ExternalSourceType.WEB and (
            self.start_time_seconds is not None or self.end_time_seconds is not None
        ):
            raise ValueError("WEB does not accept media timestamps")
        if (
            self.start_time_seconds is not None
            and self.end_time_seconds is not None
            and self.end_time_seconds <= self.start_time_seconds
        ):
            raise ValueError("end_time_seconds must be greater than start_time_seconds")

        if self.source_type is ExternalSourceType.YOUTUBE:
            assert self.url is not None
            if self.url.scheme.casefold() != "https":
                raise ValueError("YOUTUBE requires HTTPS")
            hostname = (self.url.host or "").casefold().rstrip(".")
            if hostname != "youtu.be" and not (
                hostname == "youtube.com" or hostname.endswith(".youtube.com")
            ):
                raise ValueError("YOUTUBE requires a youtube.com or youtu.be URL")
        return self


class IngestionProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(default="queued", min_length=1, max_length=100)
    percent: float = Field(default=0, ge=0, le=100)
    completed_items: int = Field(default=0, ge=0)
    total_items: int | None = Field(default=None, ge=1)
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_item_counts(self) -> "IngestionProgress":
        if self.total_items is not None and self.completed_items > self.total_items:
            raise ValueError("completed_items cannot exceed total_items")
        return self


class IngestionJobError(BaseModel):
    """A deliberately small public error; raw exceptions must never enter it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class ExternalIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: SafeIdentifier
    document_id: SafeIdentifier | None = None
    chunks_created: int = Field(ge=0)
    detected_language: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
    )
    media_duration_seconds: float | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class IngestionJob(BaseModel):
    """Immutable public snapshot of one ingestion job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_type: ExternalSourceType
    source_id: SafeIdentifier
    status: IngestionJobStatus
    progress: IngestionProgress = Field(default_factory=IngestionProgress)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ExternalIngestionResult | None = None
    error: IngestionJobError | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "IngestionJob":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot precede created_at")
        if self.completed_at is not None and self.started_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")

        if self.status is IngestionJobStatus.QUEUED:
            if any((self.started_at, self.completed_at, self.result, self.error)):
                raise ValueError("QUEUED cannot include execution or completion data")
        elif self.status is IngestionJobStatus.RUNNING:
            if self.started_at is None or any((self.completed_at, self.result, self.error)):
                raise ValueError("RUNNING requires started_at and no completion data")
        elif self.status is IngestionJobStatus.COMPLETED:
            if self.started_at is None or self.completed_at is None or self.result is None:
                raise ValueError("COMPLETED requires timestamps and result")
            if self.error is not None or self.progress.percent != 100:
                raise ValueError("COMPLETED requires 100% progress and no error")
        elif self.status is IngestionJobStatus.FAILED:
            if self.started_at is None or self.completed_at is None or self.error is None:
                raise ValueError("FAILED requires timestamps and public error")
            if self.result is not None:
                raise ValueError("FAILED cannot include a result")
        return self
