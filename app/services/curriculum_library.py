"""Small in-memory curricular library with explicit tenant/user isolation.

This is intentionally a service boundary, not a persistence implementation.
Replacing the backing dictionary with a database later must preserve the
ownership checks in this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.schemas.library import (
    CurriculumLibraryCreateRequest,
    CurriculumLibraryListResponse,
    CurriculumLibraryRecord,
    CurriculumLibraryUpdateRequest,
    LibraryStatus,
)


class CurriculumLibraryNotFoundError(LookupError):
    """The requested opaque ID does not exist in the caller's scope."""


class CurriculumLibraryOwnershipError(PermissionError):
    """The record exists but belongs to another tenant or user."""


class CurriculumLibraryVersionConflictError(ValueError):
    """An update used a stale expected version."""


class CurriculumLibrary:
    """Thread-safe process-local store.

    Tenant and user are supplied separately for every operation.  Ownership is
    checked before every read or mutation; callers can map the explicit
    ownership exception to an HTTP 403 at the API boundary.
    """

    def __init__(self) -> None:
        self._records: dict[str, CurriculumLibraryRecord] = {}
        self._lock = RLock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _validate_owner(tenant_id: str, user_id: str) -> tuple[str, str]:
        tenant_id, user_id = tenant_id.strip(), user_id.strip()
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id must not be blank")
        return tenant_id, user_id

    def _owned(
        self, curriculum_id: str, tenant_id: str, user_id: str
    ) -> CurriculumLibraryRecord:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        record = self._records.get(curriculum_id)
        if record is None:
            raise CurriculumLibraryNotFoundError(curriculum_id)
        if record.tenant_id != tenant_id or record.user_id != user_id:
            raise CurriculumLibraryOwnershipError(curriculum_id)
        return record

    def create(
        self,
        tenant_id: str,
        user_id: str,
        request: CurriculumLibraryCreateRequest,
    ) -> CurriculumLibraryRecord:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        now = self._now()
        record = CurriculumLibraryRecord(
            id=uuid4().hex,
            tenant_id=tenant_id,
            user_id=user_id,
            title=request.title,
            curriculum=request.curriculum,
            metadata=dict(request.metadata),
            status=request.status,
            version=1,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._records[record.id] = record
        return record.model_copy(deep=True)

    def get(self, curriculum_id: str, tenant_id: str, user_id: str, *, include_archived: bool = False) -> CurriculumLibraryRecord:
        with self._lock:
            record = self._owned(curriculum_id, tenant_id, user_id)
            if record.status is LibraryStatus.ARCHIVED and not include_archived:
                raise CurriculumLibraryNotFoundError(curriculum_id)
            return record.model_copy(deep=True)

    def list(self, tenant_id: str, user_id: str, *, include_archived: bool = False) -> CurriculumLibraryListResponse:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        with self._lock:
            records = [
                record.model_copy(deep=True)
                for record in self._records.values()
                if record.tenant_id == tenant_id and record.user_id == user_id
                and (include_archived or record.status is not LibraryStatus.ARCHIVED)
            ]
        records.sort(key=lambda record: (record.updated_at, record.id), reverse=True)
        return CurriculumLibraryListResponse(items=records, total=len(records))

    def update(
        self,
        curriculum_id: str,
        tenant_id: str,
        user_id: str,
        request: CurriculumLibraryUpdateRequest,
    ) -> CurriculumLibraryRecord:
        with self._lock:
            record = self._owned(curriculum_id, tenant_id, user_id)
            if record.status is LibraryStatus.ARCHIVED:
                raise ValueError("archived curricula cannot be updated")
            if request.expected_version is not None and request.expected_version != record.version:
                raise CurriculumLibraryVersionConflictError(
                    f"expected version {request.expected_version}, current is {record.version}"
                )
            changes = request.model_dump(exclude_unset=True, exclude={"expected_version"})
            if changes.get("status") is LibraryStatus.ARCHIVED:
                raise ValueError("use delete to archive a curriculum")
            updated = record.model_copy(update={**changes, "version": record.version + 1, "updated_at": self._now()}, deep=True)
            self._records[curriculum_id] = CurriculumLibraryRecord.model_validate(updated)
            return updated.model_copy(deep=True)

    def delete(self, curriculum_id: str, tenant_id: str, user_id: str) -> None:
        with self._lock:
            record = self._owned(curriculum_id, tenant_id, user_id)
            if record.status is LibraryStatus.ARCHIVED:
                return
            self._records[curriculum_id] = record.model_copy(
                update={"status": LibraryStatus.ARCHIVED, "version": record.version + 1, "updated_at": self._now()},
                deep=True,
            )
