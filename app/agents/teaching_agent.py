"""Didactic enrichment that cannot change the locked curriculum structure."""

from app.agents.prompts import TEACHING_SYSTEM_PROMPT
from app.agents.research_agent import ResearchAgent
from app.ai.interfaces.llm import StructuredGeneration, StructuredLanguageModel
from app.schemas.curriculum_schema import CurriculumDraft
from app.schemas.requests import CurriculumRequest
from app.schemas.source_resolution import EvidenceBundle


class TeachingAgent:
    _ENRICHABLE_FIELDS = (
        "didactic_explanation",
        "practical_activities",
        "evaluation_questions",
        "common_misconceptions",
        "guided_activity",
        "independent_activity",
        "formative_assessment",
        "evidence_of_learning",
    )

    def __init__(self, model: StructuredLanguageModel, research_agent: ResearchAgent | None = None) -> None:
        self._model = model
        self._research = research_agent or ResearchAgent()

    async def enrich(
        self,
        request: CurriculumRequest,
        draft: CurriculumDraft,
        evidence: EvidenceBundle | None,
    ) -> StructuredGeneration[CurriculumDraft]:
        evidence_brief = (
            self._research.build_brief(evidence)
            if evidence is not None and evidence.chunks
            else "No hay evidencia externa. No agregues citas ni fuentes."
        )
        prompt = (
            "Enriquece didácticamente el borrador y devuelve el mismo schema completo. "
            "No cambies objetivos, cantidad de unidades, nombres, subtemas, prerrequisitos, "
            "resultados, conceptos, horas ni evidence_chunk_ids.\n\n"
            f"SOLICITUD:\n{request.model_dump_json(indent=2)}\n\n"
            f"BORRADOR BLOQUEADO:\n{draft.model_dump_json(indent=2)}\n\n"
            f"{evidence_brief}"
        )
        generated = await self._model.generate_structured(
            prompt,
            response_schema=CurriculumDraft,
            system_instruction=TEACHING_SYSTEM_PROMPT,
        )
        merged = self._merge_locked_structure(draft, generated.value)
        return StructuredGeneration(value=merged, model=generated.model, usage=generated.usage)

    @classmethod
    def _merge_locked_structure(
        cls,
        original: CurriculumDraft,
        enriched: CurriculumDraft,
    ) -> CurriculumDraft:
        enriched_by_number = {unit.unit_number: unit for unit in enriched.syllabus_units}
        units = []
        for original_unit in original.syllabus_units:
            candidate = enriched_by_number.get(original_unit.unit_number)
            if candidate is None:
                units.append(original_unit)
                continue
            updates = {field: getattr(candidate, field) for field in cls._ENRICHABLE_FIELDS}
            units.append(original_unit.model_copy(update=updates))
        return original.model_copy(update={"syllabus_units": units})

