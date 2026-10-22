"""Structured curriculum architecture agent."""

from app.agents.prompts import CURRICULUM_ARCHITECT_SYSTEM_PROMPT
from app.agents.research_agent import ResearchAgent
from app.ai.interfaces.llm import StructuredGeneration, StructuredLanguageModel
from app.schemas.curriculum_schema import CurriculumDraft
from app.schemas.requests import CurriculumRequest
from app.schemas.source_resolution import EvidenceBundle


class CurriculumAgent:
    def __init__(self, model: StructuredLanguageModel, research_agent: ResearchAgent | None = None) -> None:
        self._model = model
        self._research = research_agent or ResearchAgent()

    async def design(
        self,
        request: CurriculumRequest,
        evidence: EvidenceBundle | None,
        *,
        system_prompt: str = CURRICULUM_ARCHITECT_SYSTEM_PROMPT,
    ) -> StructuredGeneration[CurriculumDraft]:
        evidence_brief = (
            self._research.build_brief(evidence)
            if evidence is not None and evidence.chunks
            else "No se proporcionó evidencia. No inventes citas ni identificadores de chunks."
        )
        allowed_chunk_ids = [chunk.chunk_id for chunk in evidence.chunks] if evidence else []
        prompt = (
            "Diseña el borrador curricular solicitado y devuelve exclusivamente el objeto del schema.\n"
            "La suma de estimated_hours de todas las unidades debe ser exactamente "
            f"{request.duration_weeks * request.hours_per_week:g} horas.\n"
            "Para cada unidad, evidence_chunk_ids sólo puede contener identificadores de la lista autorizada; "
            "déjala vacía si la evidencia no respalda esa unidad.\n\n"
            f"SOLICITUD:\n{request.model_dump_json(indent=2)}\n\n"
            f"CHUNK_IDS_AUTORIZADOS:\n{allowed_chunk_ids}\n\n"
            f"{evidence_brief}"
        )
        return await self._model.generate_structured(
            prompt,
            response_schema=CurriculumDraft,
            system_instruction=system_prompt,
        )
