"""Contracts for the tenant-scoped curricular library.

The owner identifiers are deliberately part of the persisted record, while the
create/update payloads contain only editable content.  Callers should obtain
``tenant_id`` and ``user_id`` from the authenticated request context.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.curriculum_schema import CurriculumDraft, CurriculumResponse


CurriculumArtifact = CurriculumDraft | CurriculumResponse


class LibraryStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    ARCHIVED = "ARCHIVED"


class CurriculumLibraryCreateRequest(BaseModel):
    """Editable fields used to create a saved curriculum."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    curriculum: CurriculumArtifact
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: LibraryStatus = LibraryStatus.DRAFT

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class CurriculumLibraryUpdateRequest(BaseModel):
    """Partial content update.  Version is incremented by the service."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    curriculum: CurriculumArtifact | None = None
    metadata: dict[str, Any] | None = None
    status: LibraryStatus | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def update_title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class CurriculumLibraryRecord(BaseModel):
    """A saved curriculum and its ownership/version metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=16, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    curriculum: CurriculumArtifact
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: LibraryStatus = LibraryStatus.DRAFT
    version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

    @field_validator("tenant_id", "user_id")
    @classmethod
    def owner_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("owner identifiers must not be blank")
        return value


class CurriculumLibraryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CurriculumLibraryRecord] = Field(default_factory=list)
    total: int = Field(ge=0)


# Short aliases keep imports ergonomic while preserving the explicit API names.
LibraryCreateRequest = CurriculumLibraryCreateRequest
LibraryUpdateRequest = CurriculumLibraryUpdateRequest
LibraryRecord = CurriculumLibraryRecord
LibraryListResponse = CurriculumLibraryListResponse
