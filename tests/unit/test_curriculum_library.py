from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.curriculum_schema import CurriculumDraft
from app.schemas.library import CurriculumLibraryCreateRequest, CurriculumLibraryUpdateRequest
from app.services.curriculum_library import (
    CurriculumLibrary,
    CurriculumLibraryNotFoundError,
    CurriculumLibraryOwnershipError,
    CurriculumLibraryVersionConflictError,
)


def draft(title: str = "Álgebra") -> CurriculumDraft:
    return CurriculumDraft(
        topic_title=title,
        target_level="secundaria",
        pedagogical_approach="aprendizaje activo",
        learning_objectives=["Resolver ecuaciones"],
        syllabus_units=[
            {
                "unit_number": 1,
                "unit_name": "Fundamentos",
                "estimated_hours": 2,
                "subtopics": ["Variables"],
                "didactic_explanation": "Explicación",
            }
        ],
    )


def create_request(title: str = "Álgebra") -> CurriculumLibraryCreateRequest:
    return CurriculumLibraryCreateRequest(title=title, curriculum=draft(title))


def test_library_isolates_tenant_and_user_and_does_not_leak_ids() -> None:
    library = CurriculumLibrary()
    record = library.create("tenant-a", "user-a", create_request())

    assert library.get(record.id, "tenant-a", "user-a").id == record.id
    assert library.list("tenant-a", "user-b").total == 0
    assert library.list("tenant-b", "user-a").total == 0
    with pytest.raises(CurriculumLibraryOwnershipError):
        library.get(record.id, "tenant-b", "user-a")
    with pytest.raises(CurriculumLibraryOwnershipError):
        library.delete(record.id, "tenant-a", "user-b")


def test_create_assigns_opaque_id_and_initial_version() -> None:
    record = CurriculumLibrary().create("tenant", "user", create_request())
    assert len(record.id) == 32
    assert record.id.isalnum()
    assert record.version == 1
    assert record.created_at.tzinfo is not None


def test_update_increments_version_and_supports_optimistic_locking() -> None:
    library = CurriculumLibrary()
    record = library.create("tenant", "user", create_request())
    updated = library.update(
        record.id,
        "tenant",
        "user",
        CurriculumLibraryUpdateRequest(title="Álgebra I", expected_version=1),
    )
    assert updated.title == "Álgebra I"
    assert updated.version == 2
    assert updated.updated_at >= record.updated_at
    with pytest.raises(CurriculumLibraryVersionConflictError):
        library.update(
            record.id,
            "tenant",
            "user",
            CurriculumLibraryUpdateRequest(title="stale", expected_version=1),
        )


def test_validation_rejects_blank_title_and_invalid_update_version() -> None:
    with pytest.raises(ValidationError):
        CurriculumLibraryCreateRequest(title=" ", curriculum=draft())
    with pytest.raises(ValidationError):
        CurriculumLibraryUpdateRequest(expected_version=0)
    with pytest.raises(ValueError):
        CurriculumLibrary().create(" ", "user", create_request())
