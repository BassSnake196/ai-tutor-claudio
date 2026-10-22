"""Durable SQLite implementation of the curricular library service.

SQLite is used here as a low-dependency persistence boundary for the MVP. The
JSON columns preserve the Pydantic curriculum and metadata contracts while
tenant/user ownership remains queryable in ordinary relational columns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.schemas.library import (
    CurriculumLibraryCreateRequest,
    CurriculumLibraryListResponse,
    CurriculumLibraryRecord,
    CurriculumLibraryUpdateRequest,
    LibraryStatus,
)
from app.services.curriculum_library import (
    CurriculumLibraryNotFoundError,
    CurriculumLibraryOwnershipError,
    CurriculumLibraryVersionConflictError,
)


class SQLiteCurriculumLibrary:
    """Thread-safe, file-backed implementation compatible with ``CurriculumLibrary``."""

    def __init__(self, db_path: str | Path = "data/curriculum_library.sqlite3", *, timeout: float = 5.0) -> None:
        self.db_path = str(db_path)
        self._lock = RLock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, timeout=timeout, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteCurriculumLibrary":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _validate_owner(tenant_id: str, user_id: str) -> tuple[str, str]:
        tenant_id, user_id = tenant_id.strip(), user_id.strip()
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id must not be blank")
        return tenant_id, user_id

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS curriculum_library (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    curriculum_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    version INTEGER NOT NULL CHECK (version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_curriculum_library_owner
                    ON curriculum_library (tenant_id, user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_curriculum_library_tenant
                    ON curriculum_library (tenant_id, updated_at DESC);
                """
            )
            # SQLite cannot add a CHECK constraint to an existing table, but a
            # guarded ALTER keeps pre-state databases compatible and the
            # service validates all values through the Pydantic enum.
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(curriculum_library)")}
            if "status" not in columns:
                self._connection.execute(
                    "ALTER TABLE curriculum_library ADD COLUMN status TEXT NOT NULL DEFAULT 'DRAFT'"
                )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_curriculum_library_status ON curriculum_library (status, updated_at DESC)"
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> CurriculumLibraryRecord:
        return CurriculumLibraryRecord(
            id=row["id"], tenant_id=row["tenant_id"], user_id=row["user_id"],
            title=row["title"], curriculum=json.loads(row["curriculum_json"]),
            metadata=json.loads(row["metadata_json"]), version=row["version"],
            status=LibraryStatus(row["status"] or LibraryStatus.DRAFT),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _owned(self, curriculum_id: str, tenant_id: str, user_id: str) -> sqlite3.Row:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        row = self._connection.execute(
            "SELECT * FROM curriculum_library WHERE id = ?", (curriculum_id,)
        ).fetchone()
        if row is None:
            raise CurriculumLibraryNotFoundError(curriculum_id)
        if row["tenant_id"] != tenant_id or row["user_id"] != user_id:
            raise CurriculumLibraryOwnershipError(curriculum_id)
        return row

    def create(self, tenant_id: str, user_id: str, request: CurriculumLibraryCreateRequest) -> CurriculumLibraryRecord:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        now = self._now()
        record = CurriculumLibraryRecord(
            id=uuid4().hex, tenant_id=tenant_id, user_id=user_id,
            title=request.title, curriculum=request.curriculum, metadata=dict(request.metadata),
            status=request.status,
            version=1, created_at=now, updated_at=now,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO curriculum_library
                (id, tenant_id, user_id, title, curriculum_json, metadata_json, status, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.id, record.tenant_id, record.user_id, record.title,
                 json.dumps(record.curriculum.model_dump(mode="json"), ensure_ascii=False),
                 json.dumps(record.metadata, ensure_ascii=False), record.status.value, record.version,
                 record.created_at.isoformat(), record.updated_at.isoformat()),
            )
        return record.model_copy(deep=True)

    def get(self, curriculum_id: str, tenant_id: str, user_id: str, *, include_archived: bool = False) -> CurriculumLibraryRecord:
        with self._lock:
            record = self._record(self._owned(curriculum_id, tenant_id, user_id))
            if record.status is LibraryStatus.ARCHIVED and not include_archived:
                raise CurriculumLibraryNotFoundError(curriculum_id)
            return record.model_copy(deep=True)

    def list(self, tenant_id: str, user_id: str, *, include_archived: bool = False) -> CurriculumLibraryListResponse:
        tenant_id, user_id = self._validate_owner(tenant_id, user_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM curriculum_library WHERE tenant_id = ? AND user_id = ? "
                + ("ORDER BY updated_at DESC, id DESC" if include_archived else "AND status != 'ARCHIVED' ORDER BY updated_at DESC, id DESC"),
                (tenant_id, user_id),
            ).fetchall()
        items = [self._record(row) for row in rows]
        return CurriculumLibraryListResponse(items=items, total=len(items))

    def update(self, curriculum_id: str, tenant_id: str, user_id: str, request: CurriculumLibraryUpdateRequest) -> CurriculumLibraryRecord:
        with self._lock:
            row = self._owned(curriculum_id, tenant_id, user_id)
            current = self._record(row)
            if request.expected_version is not None and request.expected_version != current.version:
                raise CurriculumLibraryVersionConflictError(
                    f"expected version {request.expected_version}, current is {current.version}"
                )
            if current.status is LibraryStatus.ARCHIVED:
                raise ValueError("archived curricula cannot be updated")
            changes = request.model_dump(exclude_unset=True, exclude={"expected_version"})
            if changes.get("status") is LibraryStatus.ARCHIVED:
                raise ValueError("use delete to archive a curriculum")
            if isinstance(changes.get("status"), LibraryStatus):
                changes["status"] = changes["status"]
            updated = current.model_copy(update={**changes, "version": current.version + 1, "updated_at": self._now()}, deep=True)
            result = self._connection.execute(
                """UPDATE curriculum_library SET title = ?, curriculum_json = ?, metadata_json = ?, status = ?,
                version = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND user_id = ? AND version = ?""",
                (updated.title, json.dumps(updated.curriculum.model_dump(mode="json"), ensure_ascii=False),
                 json.dumps(updated.metadata, ensure_ascii=False), updated.status.value, updated.version, updated.updated_at.isoformat(),
                 curriculum_id, current.tenant_id, current.user_id, current.version),
            )
            if result.rowcount != 1:
                raise CurriculumLibraryVersionConflictError("curriculum was updated concurrently")
            self._connection.commit()
            return updated.model_copy(deep=True)

    def delete(self, curriculum_id: str, tenant_id: str, user_id: str) -> None:
        with self._lock, self._connection:
            row = self._owned(curriculum_id, tenant_id, user_id)
            if row["status"] == LibraryStatus.ARCHIVED.value:
                return
            result = self._connection.execute(
                "UPDATE curriculum_library SET status = 'ARCHIVED', version = version + 1, updated_at = ? WHERE id = ? AND status != 'ARCHIVED'",
                (self._now().isoformat(), curriculum_id),
            )
            if result.rowcount != 1:
                raise CurriculumLibraryVersionConflictError("curriculum was updated concurrently")
