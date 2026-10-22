"""Deterministic curriculum checks and didactic richness metrics."""
from __future__ import annotations
import re, unicodedata
from typing import Any, Mapping
from pydantic import ValidationError
from app.schemas.curriculum_schema import CurriculumDraft, CurriculumResponse

OBSERVABLE = {"resolver", "explicar", "aplicar", "analizar", "comparar", "diseñar", "crear", "evaluar", "identificar", "calcular", "argumentar", "interpretar", "proponer", "modelar", "construir", "clasificar", "describir", "demostrar", "justificar", "formular", "programar", "estimar", "representar", "seleccionar", "organizar", "sintetizar"}
def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold()); text = "".join(c for c in text if not unicodedata.combining(c))
    return {token[:5] for token in re.findall(r"[a-záéíóúüñ]+", text) if len(token) > 2}

def validate_curriculum(task: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    try: parsed = CurriculumResponse.model_validate(response)
    except ValidationError:
        try: parsed = CurriculumDraft.model_validate(response)
        except ValidationError as exc: return {"valid": False, "errors": ["schema: " + str(exc)], "checks": {"schema": False}}
    errors: list[str] = []; checks = {"schema": True, "hours": True, "objectives_observable": True, "units": True, "alignment_structural": True, "alignment_lexical_signal": True, "didactic_nonempty": True, "citations_authorized": True, "counts": True}
    expected = float(task["weeks"]) * float(task["hours_per_week"]); actual = sum(u.estimated_hours for u in parsed.syllabus_units)
    if abs(actual - expected) > .01: checks["hours"] = False; errors.append(f"hours: expected {expected}, got {actual}")
    for objective in parsed.learning_objectives:
        first = objective.strip().casefold().split(" ", 1)[0].rstrip(":;,. ")
        if first not in OBSERVABLE: checks["objectives_observable"] = False; errors.append(f"objective must start with recognized infinitive: {first}")
    if len(parsed.syllabus_units) != int(task.get("expected_units", len(parsed.syllabus_units))): checks["units"] = False; errors.append("unit count mismatch")
    objective_tokens = set().union(*(_tokens(x) for x in parsed.learning_objectives)) if parsed.learning_objectives else set()
    for unit in parsed.syllabus_units:
        structural = bool(unit.learning_outcomes and (unit.guided_activity or unit.practical_activities) and (unit.formative_assessment or unit.evaluation_questions) and unit.evidence_of_learning)
        if not structural: checks["alignment_structural"] = False; errors.append(f"structural alignment incomplete in unit {unit.unit_number}")
        signal = bool(objective_tokens & set().union(*(_tokens(x) for x in unit.subtopics))) if unit.subtopics else False
        if not signal: checks["alignment_lexical_signal"] = False
        if not unit.didactic_explanation.strip(): checks["didactic_nonempty"] = False; errors.append("empty didactic field")
        allowed = set(task.get("source_ids", []))
        if any(c.source_id not in allowed for c in getattr(unit, "citations", [])): checks["citations_authorized"] = False; errors.append(f"unauthorized citation in unit {unit.unit_number}")
        if len(unit.practical_activities) > 20 or len(unit.evaluation_questions) > 20: checks["counts"] = False; errors.append("activity/question count exceeds limit")
    return {"valid": not errors, "errors": errors, "checks": checks, "topic_title": parsed.topic_title, "unit_count": len(parsed.syllabus_units), "total_hours": actual, "richness": richness_metrics(parsed)}

def richness_metrics(parsed: CurriculumResponse) -> dict[str, float]:
    units = parsed.syllabus_units; n = max(len(units), 1)
    return {"complete_didactic_fields_rate": sum(bool(u.guided_activity and u.independent_activity and u.formative_assessment and u.evidence_of_learning) for u in units) / n, "activities_per_unit": sum(len(u.practical_activities) for u in units) / n, "questions_per_unit": sum(len(u.evaluation_questions) for u in units) / n, "common_misconceptions_per_unit": sum(len(u.common_misconceptions) for u in units) / n}
