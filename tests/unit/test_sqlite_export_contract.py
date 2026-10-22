"""Contract checks for the future durable curriculum repository.

The application currently has an in-memory library (see BLOCK_4_PLAN.md), so
the repository-specific test is intentionally skipped until a SQLite adapter is
introduced.  The helper is already executable against any adapter implementing
``save_json``/``load_json`` and protects the canonical export invariant.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from collections.abc import Callable

import pytest

from app.schemas.curriculum_schema import CurriculumResponse
from app.services.curriculum_export import render_curriculum_json


def assert_json_export_round_trip(
    curriculum: CurriculumResponse,
    save_json: Callable[[str], None],
    load_json: Callable[[], str],
) -> None:
    """Assert the adapter preserves the exact canonical JSON export."""

    before = render_curriculum_json(curriculum)
    save_json(before)
    after = render_curriculum_json(CurriculumResponse.model_validate(json.loads(load_json())))
    assert after == before


def _curriculum() -> CurriculumResponse:
    return CurriculumResponse.model_validate(
        {
            "topic_title": "Álgebra",
            "target_level": "Secundaria",
            "pedagogical_approach": "Problemas",
            "learning_objectives": ["Resolver ecuaciones"],
            "syllabus_units": [
                {
                    "unit_number": 1,
                    "unit_name": "Variables",
                    "estimated_hours": 2,
                    "subtopics": ["Símbolos"],
                    "didactic_explanation": "De lo concreto a lo simbólico.",
                    "citations": [],
                }
            ],
            "grounding_status": "SUPPORTED",
        }
    )


def test_contract_preserves_canonical_json_in_sqlite_instance() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE curriculum_versions (json_payload TEXT NOT NULL)")

    def save_json(payload: str) -> None:
        connection.execute("DELETE FROM curriculum_versions")
        connection.execute("INSERT INTO curriculum_versions VALUES (?)", (payload,))
        connection.commit()

    def load_json() -> str:
        row = connection.execute("SELECT json_payload FROM curriculum_versions").fetchone()
        assert row is not None
        return row[0]

    assert_json_export_round_trip(_curriculum(), save_json, load_json)
    connection.close()


def test_application_sqlite_repository_contract_is_pending_until_importable() -> None:
    """Document the handoff point without failing before the repository exists."""

    try:
        repository_spec = importlib.util.find_spec("app.persistence.sqlite_repository")
    except ModuleNotFoundError:
        repository_spec = None
    if repository_spec is None:
        pytest.skip("SQLite application repository is not implemented yet")
    pytest.skip("SQLite adapter API must be wired to assert_json_export_round_trip")
