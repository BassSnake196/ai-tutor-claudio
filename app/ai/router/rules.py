from dataclasses import dataclass
from enum import StrEnum


class RouteKind(StrEnum):
    LOCAL = "LOCAL"
    RETRIEVAL = "RETRIEVAL"
    CLOUD = "CLOUD"


@dataclass(frozen=True)
class RoutingInput:
    prompt: str
    requires_sources: bool = False


@dataclass(frozen=True)
class RouteDecision:
    route: RouteKind
    intent: str
    reason: str


class RuleBasedRouter:
    """Cheap and explainable routing; an SLM fallback can be added later."""

    _curriculum_terms = (
        "temario",
        "plan de clase",
        "planifica",
        "planificar",
        "curso completo",
        "rúbrica",
        "rubrica",
        "competencias",
        "taxonomía de bloom",
    )
    _source_terms = ("documento", "fuente", "bibliografía", "bibliografia", "archivo", "cita")

    def decide(self, request: RoutingInput) -> RouteDecision:
        text = request.prompt.casefold()
        if request.requires_sources or any(term in text for term in self._source_terms):
            return RouteDecision(RouteKind.RETRIEVAL, "source_question", "La consulta exige evidencia recuperable.")
        if any(term in text for term in self._curriculum_terms):
            return RouteDecision(RouteKind.CLOUD, "pedagogical_generation", "La solicitud requiere diseño pedagógico complejo.")
        return RouteDecision(RouteKind.LOCAL, "general_question", "La solicitud es de bajo riesgo y no requiere fuentes.")
