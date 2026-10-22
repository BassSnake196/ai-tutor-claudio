import json

import pytest
from pydantic import ValidationError

from app.schemas.curriculum_schema import CurriculumResponse
from app.services.curriculum_export import (
    render_curriculum_json,
    render_curriculum_markdown,
)
from app.schemas.sources import GroundingStatus


def sample() -> CurriculumResponse:
    return CurriculumResponse.model_validate(
        {
            "topic_title": "Álgebra básica",
            "target_level": "Secundaria",
            "pedagogical_approach": "Resolución de problemas",
            "learning_objectives": ["Resolver ecuaciones lineales"],
            "syllabus_units": [
                {
                    "unit_number": 1,
                    "unit_name": "Ecuaciones",
                    "estimated_hours": 3,
                    "subtopics": ["Variables", "Igualdad"],
                    "didactic_explanation": "Usar una balanza como modelo.",
                    "guided_activity": "Modelar un ejemplo.",
                    "evaluation_questions": [
                        {
                            "question": "¿Qué conserva la igualdad?",
                            "expected_answer": "La misma operación en ambos miembros.",
                        }
                    ],
                    "citations": [
                        {
                            "source_id": "doc-1",
                            "fragment_reference": "doc-1#chunk-2",
                            "timestamp_start": 2.5,
                            "timestamp_end": 8,
                        }
                    ],
                }
            ],
            "grounding_status": GroundingStatus.SUPPORTED,
        }
    )


def test_markdown_contains_teaching_content_grounding_and_citation() -> None:
    output = render_curriculum_markdown(sample())

    assert "# Álgebra básica" in output
    assert "`SUPPORTED`" in output
    assert "Actividad guiada" in output
    assert "doc-1#chunk-2" in output
    assert "inicio=2.5s" in output and "fin=8s" in output


def test_json_is_valid_stable_and_contains_only_public_contract() -> None:
    output = render_curriculum_json(sample())
    parsed = json.loads(output)

    assert parsed["grounding_status"] == "SUPPORTED"
    assert parsed["syllabus_units"][0]["citations"][0]["source_id"] == "doc-1"
    assert "storage_path" not in output
    assert "api_key" not in output.lower()
    assert output == render_curriculum_json(sample())


def test_invalid_payload_is_rejected_by_pydantic() -> None:
    payload = sample().model_dump()
    payload["provider_api_key"] = "sk-secret-value-that-must-not-export"

    with pytest.raises(ValidationError):
        render_curriculum_json(payload)


def test_secret_like_text_is_redacted_in_markdown() -> None:
    payload = sample().model_dump()
    payload["syllabus_units"][0]["didactic_explanation"] = (
        "No copiar AIza123456789012345678901234567890."
    )

    output = render_curriculum_markdown(payload)
    assert "AIza123" not in output
    assert "[REDACTED_API_KEY]" in output

