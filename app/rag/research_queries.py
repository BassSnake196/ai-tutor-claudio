"""Deterministic research queries used by the curriculum source resolver.

The first implementation deliberately avoids an LLM call.  Keeping this step
deterministic makes source-isolation and coverage tests reproducible, and saves
one cloud request for every curriculum generated.
"""

from dataclasses import dataclass
from typing import Any, Iterable

from app.schemas.source_resolution import ResearchCategory

CONCEPTS = ResearchCategory.CONCEPTS
PROGRESSION = ResearchCategory.PROGRESSION
DIDACTICS = ResearchCategory.DIDACTICS
ASSESSMENT = ResearchCategory.ASSESSMENT
REQUIREMENTS = ResearchCategory.CURRICULUM_REQUIREMENTS

CORE_RESEARCH_CATEGORIES = (CONCEPTS, PROGRESSION, DIDACTICS, ASSESSMENT)


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    category: ResearchCategory
    query: str


def _value(request: Any, name: str, default: Any = None) -> Any:
    if isinstance(request, dict):
        return request.get(name, default)
    return getattr(request, name, default)


def _compact_items(items: Iterable[Any] | None, *, limit: int = 4) -> str:
    if not items:
        return ""
    unique: list[str] = []
    for item in items:
        value = " ".join(str(item).split())[:500]
        if value and value not in unique:
            unique.append(value)
        if len(unique) == limit:
            break
    return "; ".join(unique)


def build_research_queries(request: Any) -> tuple[ResearchQuery, ...]:
    """Build four core queries and, when useful, one requirements query.

    ``request`` intentionally uses structural typing so this module can be used
    with the Pydantic API contract as well as small test fixtures.
    """

    topic_value = _value(request, "topic", "")
    level_value = _value(request, "target_level", "")
    topic = " ".join(str(topic_value or "").split())
    level = " ".join(str(level_value or "").split())
    if not topic:
        raise ValueError("La solicitud curricular debe incluir un tema.")
    if not level:
        raise ValueError("La solicitud curricular debe incluir un nivel objetivo.")

    prior = _compact_items(_value(request, "prior_knowledge", ()))
    outcomes = _compact_items(_value(request, "desired_outcomes", ()))
    constraints = _compact_items(_value(request, "constraints", ()))
    approach_value = _value(request, "pedagogical_approach", "")
    approach = " ".join(str(approach_value or "").split())[:500]
    audience = f"{topic} para nivel {level}"

    queries = [
        ResearchQuery(
            CONCEPTS,
            f"{audience}: conceptos fundamentales, definiciones y prerrequisitos necesarios",
        ),
        ResearchQuery(
            PROGRESSION,
            f"{audience}: secuencia de aprendizaje, progresión de dificultad y conexiones entre conceptos",
        ),
        ResearchQuery(
            DIDACTICS,
            f"{audience}: errores frecuentes, explicaciones didácticas, ejemplos y actividades de práctica",
        ),
        ResearchQuery(
            ASSESSMENT,
            f"{audience}: evaluación diagnóstica, formativa e integradora con criterios observables",
        ),
    ]

    requirement_parts = []
    if prior:
        requirement_parts.append(f"conocimientos previos: {prior}")
    if outcomes:
        requirement_parts.append(f"resultados deseados: {outcomes}")
    if approach:
        requirement_parts.append(f"enfoque pedagógico: {approach}")
    if constraints:
        requirement_parts.append(f"restricciones: {constraints}")
    if requirement_parts:
        queries.append(
            ResearchQuery(
                REQUIREMENTS,
                f"{audience}: requisitos de diseño curricular; " + "; ".join(requirement_parts),
            )
        )

    return tuple(queries)
