from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.agents.prompts import CRITIC_SYSTEM_PROMPT
from app.agents.evidence_serialization import serialize_evidence
from app.ai.interfaces.llm import LanguageModel, TokenUsage
from app.schemas.curriculum_schema import CurriculumDraft, CurriculumResponse, SyllabusUnit
from app.schemas.requests import CurriculumRequest
from app.schemas.source_resolution import EvidenceBundle, SourcePolicy
from app.schemas.responses import Citation, GroundingStatus


class GroundingAuditor:
    """Deterministically verifies that every cited fragment was retrieved."""

    def assess(self, citations: list[Citation], available_source_ids: set[str]) -> GroundingStatus:
        if not citations:
            return GroundingStatus.INSUFFICIENT_CONTEXT
        cited_ids = {citation.source_id for citation in citations}
        if cited_ids.issubset(available_source_ids):
            return GroundingStatus.SUPPORTED
        if cited_ids.intersection(available_source_ids):
            return GroundingStatus.PARTIALLY_SUPPORTED
        return GroundingStatus.UNSUPPORTED


@dataclass(frozen=True)
class CurriculumAuditResult:
    curriculum: CurriculumResponse
    warnings: list[str]


class CurriculumCritic:
    """Audits locked structure and maps only retrieved chunk IDs to citations."""

    def finalize(
        self,
        request: CurriculumRequest,
        draft: CurriculumDraft,
        evidence: EvidenceBundle | None,
    ) -> CurriculumAuditResult:
        warnings: list[str] = []
        evidence_by_id = {chunk.chunk_id: chunk for chunk in evidence.chunks} if evidence else {}
        invalid_refs: set[str] = set()
        units_with_valid_evidence = 0
        final_units: list[SyllabusUnit] = []

        for unit in draft.syllabus_units:
            citations: list[Citation] = []
            for chunk_id in dict.fromkeys(unit.evidence_chunk_ids):
                chunk = evidence_by_id.get(chunk_id)
                if chunk is None:
                    invalid_refs.add(chunk_id)
                    continue
                citations.append(
                    Citation(
                        source_id=chunk.metadata.source_id,
                        fragment_reference=chunk.fragment_reference,
                        timestamp_start=chunk.metadata.timestamp_start,
                        timestamp_end=chunk.metadata.timestamp_end,
                    )
                )
            if citations:
                units_with_valid_evidence += 1
            final_units.append(SyllabusUnit(**unit.model_dump(), citations=citations))

            if not unit.learning_outcomes:
                warnings.append(f"La unidad {unit.unit_number} no declara resultados de aprendizaje.")
            if not unit.practical_activities and not unit.guided_activity:
                warnings.append(f"La unidad {unit.unit_number} no incluye práctica guiada o aplicada.")
            if not unit.evaluation_questions and not unit.formative_assessment:
                warnings.append(f"La unidad {unit.unit_number} no incluye evaluación verificable.")

        if invalid_refs:
            warnings.append(
                "Se descartaron referencias no recuperadas: " + ", ".join(sorted(invalid_refs))
            )

        target_hours = request.duration_weeks * request.hours_per_week
        actual_hours = sum(unit.estimated_hours for unit in final_units)
        if abs(actual_hours - target_hours) > 0.01:
            warnings.append(
                f"La carga declarada ({actual_hours:g} h) no coincide con la solicitada ({target_hours:g} h)."
            )

        grounding = self._grounding_status(
            request.source_policy,
            evidence,
            units_with_valid_evidence,
            len(final_units),
            bool(invalid_refs),
        )
        curriculum = CurriculumResponse(
            schema_version=draft.schema_version,
            topic_title=draft.topic_title,
            target_level=draft.target_level,
            pedagogical_approach=draft.pedagogical_approach,
            learning_objectives=draft.learning_objectives,
            syllabus_units=final_units,
            grounding_status=grounding,
        )
        return CurriculumAuditResult(curriculum=curriculum, warnings=list(dict.fromkeys(warnings)))

    @staticmethod
    def _grounding_status(
        policy: SourcePolicy,
        evidence: EvidenceBundle | None,
        units_with_evidence: int,
        unit_count: int,
        has_invalid_refs: bool,
    ) -> GroundingStatus:
        if policy is SourcePolicy.NO_SOURCES:
            return GroundingStatus.UNSUPPORTED
        if evidence is None or not evidence.chunks:
            return GroundingStatus.INSUFFICIENT_CONTEXT
        if evidence.contradictions:
            return GroundingStatus.CONTRADICTORY_SOURCES
        if units_with_evidence == unit_count and not has_invalid_refs and evidence.coverage.sufficient:
            return GroundingStatus.SUPPORTED
        if units_with_evidence:
            return GroundingStatus.PARTIALLY_SUPPORTED
        return GroundingStatus.UNSUPPORTED


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class SemanticAuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: FindingSeverity
    location: str = Field(min_length=1, max_length=500)
    issue: str = Field(min_length=1, max_length=2_000)
    correction: str | None = Field(default=None, max_length=2_000)


class SemanticAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: GroundingStatus
    findings: list[SemanticAuditFinding] = Field(default_factory=list, max_length=5)


class SemanticCurriculumCritic:
    """Best-effort local semantic audit; it may downgrade but never upgrade grounding."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model
        self.last_usage = TokenUsage()

    async def audit(
        self,
        curriculum: CurriculumResponse,
        evidence: EvidenceBundle | None,
    ) -> SemanticAuditReport:
        evidence_payload = serialize_evidence(evidence)
        prompt = (
            "Audita el currículo y devuelve exclusivamente JSON con esta forma: "
            '{"verdict":"SUPPORTED|PARTIALLY_SUPPORTED|INSUFFICIENT_CONTEXT|UNSUPPORTED|CONTRADICTORY_SOURCES",'
            '"findings":[{"severity":"INFO|WARNING|ERROR","location":"...","issue":"...",'
            '"correction":"... o null"}]}. '
            "No incluyas markdown. No inventes evidencia. Devuelve como máximo 5 hallazgos, "
            "cada location, issue y correction debe ser una frase breve de menos de 120 caracteres.\n\n"
            f"CURRÍCULO:\n{curriculum.model_dump_json(indent=2)}\n\n"
            f"EVIDENCIA AUTORIZADA:\n{evidence_payload}"
        )
        generate_with_usage = getattr(self._model, "generate_with_usage", None)
        if callable(generate_with_usage):
            generation = await generate_with_usage(
                prompt,
                system_instruction=CRITIC_SYSTEM_PROMPT,
            )
            raw = generation.text
            self.last_usage = generation.usage
        else:
            raw = await self._model.generate(prompt, system_instruction=CRITIC_SYSTEM_PROMPT)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```")
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return SemanticAuditReport.model_validate_json(cleaned.strip())

    @staticmethod
    def apply_downgrade(
        curriculum: CurriculumResponse,
        report: SemanticAuditReport,
    ) -> CurriculumResponse:
        current = curriculum.grounding_status
        if current is GroundingStatus.CONTRADICTORY_SOURCES:
            return curriculum
        if report.verdict is GroundingStatus.CONTRADICTORY_SOURCES:
            return curriculum.model_copy(update={"grounding_status": report.verdict})

        rank = {
            GroundingStatus.SUPPORTED: 4,
            GroundingStatus.PARTIALLY_SUPPORTED: 3,
            GroundingStatus.UNSUPPORTED: 2,
            GroundingStatus.INSUFFICIENT_CONTEXT: 1,
            GroundingStatus.CONTRADICTORY_SOURCES: 0,
        }
        if rank[report.verdict] < rank[current]:
            return curriculum.model_copy(update={"grounding_status": report.verdict})
        return curriculum
