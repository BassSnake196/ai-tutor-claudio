"""Coverage rules for evidence collected by the hierarchical resolver."""

from typing import Any, Iterable

from app.schemas.source_resolution import CoverageReport, ResearchCategory


CORE_RESEARCH_CATEGORIES = (
    ResearchCategory.CONCEPTS,
    ResearchCategory.PROGRESSION,
    ResearchCategory.DIDACTICS,
    ResearchCategory.ASSESSMENT,
)


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _categories(item: Any) -> set[ResearchCategory]:
    values = _field(item, "research_categories")
    if values:
        return {ResearchCategory(value) for value in values}
    value = _field(item, "research_category", _field(item, "category"))
    return {ResearchCategory(value)} if value else set()


def assess_coverage(
    chunks: Iterable[Any],
    *,
    required_categories: tuple[ResearchCategory, ...] = CORE_RESEARCH_CATEGORIES,
    mandatory_category: ResearchCategory = ResearchCategory.CONCEPTS,
    minimum_categories: int = 3,
    minimum_chunks: int = 4,
) -> CoverageReport:
    """Evaluate category and unique-chunk coverage with explicit baselines."""

    if not required_categories:
        raise ValueError("Debe existir al menos una categoría de cobertura.")
    if mandatory_category not in required_categories:
        raise ValueError("La categoría obligatoria debe pertenecer a las requeridas.")
    if not 1 <= minimum_categories <= len(required_categories):
        raise ValueError("minimum_categories está fuera del rango permitido.")
    if minimum_chunks < 1:
        raise ValueError("minimum_chunks debe ser mayor que cero.")

    present: set[ResearchCategory] = set()
    identities: set[str] = set()
    for index, chunk in enumerate(chunks):
        present.update(_categories(chunk))
        chunk_id = _field(chunk, "chunk_id")
        content_hash = _field(chunk, "content_hash")
        identities.add(str(chunk_id or content_hash or f"anonymous:{index}"))

    covered = tuple(category for category in required_categories if category in present)
    missing = tuple(category for category in required_categories if category not in present)
    score = len(covered) / len(required_categories)
    sufficient = (
        mandatory_category in present
        and len(covered) >= minimum_categories
        and len(identities) >= minimum_chunks
    )
    return CoverageReport(
        required_categories=list(required_categories),
        covered_categories=list(covered),
        missing_categories=list(missing),
        unique_chunks=len(identities),
        score=score,
        sufficient=sufficient,
    )
