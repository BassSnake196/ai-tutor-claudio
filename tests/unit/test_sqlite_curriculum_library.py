from pathlib import Path
import sqlite3

import pytest

from app.services.curriculum_library import CurriculumLibraryOwnershipError, CurriculumLibraryVersionConflictError
from app.schemas.library import CurriculumLibraryUpdateRequest, LibraryStatus
from app.services.sqlite_curriculum_library import SQLiteCurriculumLibrary
from tests.unit.test_curriculum_library import create_request


def test_sqlite_persists_across_service_instances(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    first = SQLiteCurriculumLibrary(path)
    created = first.create("tenant-a", "user-a", create_request())
    first.close()

    second = SQLiteCurriculumLibrary(path)
    loaded = second.get(created.id, "tenant-a", "user-a")
    assert loaded.id == created.id
    assert loaded.curriculum.topic_title == "Álgebra"
    second.close()


def test_sqlite_enforces_scope_and_delete(tmp_path: Path) -> None:
    library = SQLiteCurriculumLibrary(tmp_path / "library.sqlite3")
    created = library.create("tenant-a", "user-a", create_request())
    with pytest.raises(CurriculumLibraryOwnershipError):
        library.get(created.id, "tenant-b", "user-a")
    with pytest.raises(CurriculumLibraryOwnershipError):
        library.delete(created.id, "tenant-a", "user-b")
    library.delete(created.id, "tenant-a", "user-a")
    assert library.list("tenant-a", "user-a").total == 0
    assert library.list("tenant-a", "user-a", include_archived=True).total == 1
    assert library.get(created.id, "tenant-a", "user-a", include_archived=True).status is LibraryStatus.ARCHIVED
    library.close()


def test_sqlite_delete_is_logical_and_reopen_preserves_archived_state(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    first = SQLiteCurriculumLibrary(path)
    created = first.create("tenant-a", "user-a", create_request())
    first.delete(created.id, "tenant-a", "user-a")
    first.close()
    second = SQLiteCurriculumLibrary(path)
    archived = second.get(created.id, "tenant-a", "user-a", include_archived=True)
    assert archived.status is LibraryStatus.ARCHIVED
    assert archived.version == 2
    second.close()


def test_sqlite_version_conflict_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    first = SQLiteCurriculumLibrary(path)
    created = first.create("tenant-a", "user-a", create_request())
    updated = first.update(created.id, "tenant-a", "user-a", CurriculumLibraryUpdateRequest(title="v2", expected_version=1))
    first.close()

    second = SQLiteCurriculumLibrary(path)
    assert second.get(created.id, "tenant-a", "user-a").version == 2
    with pytest.raises(CurriculumLibraryVersionConflictError):
        second.update(created.id, "tenant-a", "user-a", CurriculumLibraryUpdateRequest(title="stale", expected_version=1))
    second.close()


def test_sqlite_migrates_legacy_table_without_losing_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE curriculum_library (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
        title TEXT NOT NULL, curriculum_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
        version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
    )
    connection.commit()
    connection.close()
    library = SQLiteCurriculumLibrary(path)
    columns = {row["name"] for row in library._connection.execute("PRAGMA table_info(curriculum_library)")}
    assert "status" in columns
    created = library.create("tenant-a", "user-a", create_request())
    assert created.status is LibraryStatus.DRAFT
    library.close()
