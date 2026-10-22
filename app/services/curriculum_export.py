"""Deterministic, safe exports for audited curricula.

Exports intentionally accept the public ``CurriculumResponse`` contract only.
There are no model or network calls here, which makes the output reproducible
and suitable for download or snapshot testing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from pydantic import ValidationError

from app.schemas.curriculum_schema import CurriculumResponse


# These patterns cover the credentials that could accidentally be pasted into
# generated text or a source identifier.  Redaction is deterministic and keeps
# the export useful while ensuring credentials are never emitted.
_SECRET_PATTERNS = (
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE), "[REDACTED_TOKEN]"),
)


def validate_curriculum(value: CurriculumResponse | Mapping[str, object]) -> CurriculumResponse:
    """Validate an export input against the audited Pydantic schema.

    ``extra='forbid'`` on the schema rejects provider metadata, API keys, and
    other fields that are not part of the teacher-facing artifact.
    """

    try:
        return value if isinstance(value, CurriculumResponse) else CurriculumResponse.model_validate(value)
    except ValidationError:
        # Preserve Pydantic's detailed validation error for callers and tests.
        raise


def _safe_text(value: str) -> str:
    text = value.replace("\\", "\\\\")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _inline(value: str) -> str:
    """Escape Markdown punctuation without changing line structure."""

    text = _safe_text(value)
    return re.sub(r"([`*_\[\]<>|])", r"\\\1", text)


def _citation_line(citation: Mapping[str, object]) -> str:
    reference = _inline(str(citation["fragment_reference"]))
    source_id = _inline(str(citation["source_id"]))
    timestamps: list[str] = []
    if citation.get("timestamp_start") is not None:
        timestamps.append(f"inicio={float(citation['timestamp_start']):g}s")
    if citation.get("timestamp_end") is not None:
        timestamps.append(f"fin={float(citation['timestamp_end']):g}s")
    suffix = f" ({', '.join(timestamps)})" if timestamps else ""
    return f"- `{source_id}` — `{reference}`{suffix}"


def render_curriculum_markdown(value: CurriculumResponse | Mapping[str, object]) -> str:
    """Render a validated curriculum as teacher-readable Markdown."""

    curriculum = validate_curriculum(value)
    data = curriculum.model_dump(mode="json")
    lines = [
        f"# {_inline(data['topic_title'])}",
        "",
        f"**Nivel:** {_inline(data['target_level'])}  ",
        f"**Enfoque pedagógico:** {_inline(data['pedagogical_approach'])}",
        "",
        "## Estado de fundamentación",
        "",
        f"`{data['grounding_status']}`",
        "",
        "## Objetivos de aprendizaje",
        "",
    ]
    lines.extend(f"- {_inline(item)}" for item in data["learning_objectives"])

    for unit in data["syllabus_units"]:
        lines.extend(
            [
                "",
                f"## Unidad {unit['unit_number']}: {_inline(unit['unit_name'])}",
                "",
                f"**Horas estimadas:** {unit['estimated_hours']}",
                "",
                "### Subtemas",
                "",
            ]
        )
        lines.extend(f"- {_inline(item)}" for item in unit["subtopics"])
        lines.extend(["", "### Explicación didáctica", "", _safe_text(unit["didactic_explanation"])])
        for heading, key in (
            ("Resultados de aprendizaje", "learning_outcomes"),
            ("Conceptos esenciales", "essential_concepts"),
            ("Prerrequisitos", "prerequisites"),
            ("Actividades prácticas", "practical_activities"),
            ("Ideas previas frecuentes", "common_misconceptions"),
            ("Evidencias de aprendizaje", "evidence_of_learning"),
        ):
            if unit[key]:
                lines.extend(["", f"### {heading}", ""])
                lines.extend(f"- {_inline(item)}" for item in unit[key])
        for heading, key in (
            ("Actividad guiada", "guided_activity"),
            ("Actividad independiente", "independent_activity"),
            ("Evaluación formativa", "formative_assessment"),
        ):
            if unit[key]:
                lines.extend(["", f"### {heading}", "", _safe_text(unit[key])])
        if unit["evaluation_questions"]:
            lines.extend(["", "### Preguntas de evaluación", ""])
            for question in unit["evaluation_questions"]:
                lines.extend(
                    [
                        f"- **Pregunta:** {_inline(question['question'])}",
                        f"  **Respuesta esperada:** {_inline(question['expected_answer'])}",
                    ]
                )
        lines.extend(["", "### Fuentes y citas", ""])
        if unit["citations"]:
            lines.extend(_citation_line(citation) for citation in unit["citations"])
        else:
            lines.append("- No se proporcionaron citas para esta unidad.")

    return "\n".join(lines).rstrip() + "\n"


def render_curriculum_json(value: CurriculumResponse | Mapping[str, object]) -> str:
    """Render a validated curriculum as stable, UTF-8 JSON."""

    curriculum = validate_curriculum(value)
    return json.dumps(
        curriculum.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


# Explicit export-oriented aliases make the service discoverable to callers.
export_curriculum_markdown = render_curriculum_markdown
export_curriculum_json = render_curriculum_json
