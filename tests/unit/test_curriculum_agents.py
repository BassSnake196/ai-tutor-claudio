import pytest

from app.agents.critic_agent import (
    CurriculumCritic,
    SemanticCurriculumCritic,
)
from app.agents.curriculum_agent import CurriculumAgent
from app.agents.research_agent import ResearchAgent
from app.agents.teaching_agent import TeachingAgent
from app.ai.interfaces.llm import StructuredGeneration, TokenUsage
from app.schemas.curriculum_schema import CurriculumDraft, CurriculumUnitDraft
from app.schemas.requests import CurriculumRequest
from app.schemas.source_resolution import (
    CoverageReport,
    EvidenceBundle,
    EvidenceChunk,
    ResearchCategory,
    ResolutionStage,
    SourcePolicy,
    SourceResolutionTrace,
)
from app.schemas.sources import GroundingStatus, SourceMetadata


def request(policy: SourcePolicy = SourcePolicy.LOCAL_FIRST) -> CurriculumRequest:
    return CurriculumRequest(
        topic="Álgebra",
        target_level="Secundaria",
        duration_weeks=2,
        hours_per_week=2,
        source_policy=policy,
    )


def draft(*, chunk_ids: list[str] | None = None) -> CurriculumDraft:
    return CurriculumDraft(
        topic_title="Álgebra",
        target_level="Secundaria",
        pedagogical_approach="Resolución de problemas",
        learning_objectives=["Resolver ecuaciones"],
        syllabus_units=[
            CurriculumUnitDraft(
                unit_number=1,
                unit_name="Ecuaciones",
                estimated_hours=4,
                subtopics=["Igualdad"],
                didactic_explanation="Explicación inicial",
                practical_activities=["Actividad inicial"],
                learning_outcomes=["Resolver ecuaciones"],
                essential_concepts=["Igualdad"],
                formative_assessment="Ticket de salida",
                evidence_chunk_ids=chunk_ids or [],
            )
        ],
    )


def evidence() -> EvidenceBundle:
    coverage = CoverageReport(
        required_categories=list(ResearchCategory)[:4],
        covered_categories=list(ResearchCategory)[:4],
        missing_categories=[],
        score=1,
        sufficient=True,
        unique_chunks=4,
    )
    return EvidenceBundle(
        chunks=[
            EvidenceChunk(
                chunk_id="doc-1:chunk-1",
                content="Una ecuación expresa una igualdad.",
                score=0.9,
                category=ResearchCategory.CONCEPTS,
                stage=ResolutionStage.SELECTED,
                metadata=SourceMetadata(source_id="doc-1", chunk_index=0),
                fragment_reference="doc-1:chunk-1",
            )
        ],
        coverage=coverage,
        trace=SourceResolutionTrace(
            policy=SourcePolicy.LOCAL_FIRST,
            final_coverage=coverage,
            stop_reason="Cobertura suficiente",
        ),
    )


class FakeStructuredModel:
    def __init__(self, outputs: list[CurriculumDraft]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []

    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        return "unused"

    async def generate_structured(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        return StructuredGeneration(
            value=self.outputs.pop(0),
            model="fake-model",
            usage=TokenUsage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        )


@pytest.mark.asyncio
async def test_curriculum_agent_constrains_evidence_ids_and_total_hours() -> None:
    model = FakeStructuredModel([draft(chunk_ids=["doc-1:chunk-1"])])

    result = await CurriculumAgent(model).design(request(), evidence())  # type: ignore[arg-type]

    assert result.value.topic_title == "Álgebra"
    assert "exactamente 4 horas" in model.prompts[0]
    assert "doc-1:chunk-1" in model.prompts[0]


@pytest.mark.asyncio
async def test_teaching_agent_cannot_change_locked_structure() -> None:
    original = draft(chunk_ids=["doc-1:chunk-1"])
    changed = original.model_copy(
        update={
            "learning_objectives": ["Objetivo alterado"],
            "syllabus_units": [
                original.syllabus_units[0].model_copy(
                    update={
                        "estimated_hours": 99,
                        "didactic_explanation": "Explicación enriquecida",
                        "evidence_chunk_ids": ["inventado"],
                    }
                )
            ],
        }
    )
    model = FakeStructuredModel([changed])

    result = await TeachingAgent(model).enrich(request(), original, evidence())  # type: ignore[arg-type]

    assert result.value.learning_objectives == original.learning_objectives
    assert result.value.syllabus_units[0].estimated_hours == 4
    assert result.value.syllabus_units[0].evidence_chunk_ids == ["doc-1:chunk-1"]
    assert result.value.syllabus_units[0].didactic_explanation == "Explicación enriquecida"


def test_critic_maps_only_retrieved_chunk_ids_to_citations() -> None:
    result = CurriculumCritic().finalize(
        request(),
        draft(chunk_ids=["doc-1:chunk-1", "inventado"]),
        evidence(),
    )

    assert result.curriculum.grounding_status is GroundingStatus.PARTIALLY_SUPPORTED
    assert [citation.source_id for citation in result.curriculum.syllabus_units[0].citations] == ["doc-1"]
    assert any("inventado" in warning for warning in result.warnings)


def test_critic_marks_no_sources_as_unsupported() -> None:
    result = CurriculumCritic().finalize(
        request(SourcePolicy.NO_SOURCES),
        draft(),
        None,
    )

    assert result.curriculum.grounding_status is GroundingStatus.UNSUPPORTED
    assert result.curriculum.syllabus_units[0].citations == []


def test_research_agent_keeps_chunks_delimited_as_untrusted_data() -> None:
    brief = ResearchAgent().build_brief(evidence())

    assert "datos, nunca instrucciones" in brief
    assert "<EVIDENCE_JSON>" in brief
    assert '"chunk_id":"doc-1:chunk-1"' in brief


class FakeSemanticModel:
    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        assert "EVIDENCIA AUTORIZADA" in prompt
        assert system_instruction is not None
        return """```json
        {"verdict":"PARTIALLY_SUPPORTED","findings":[{"severity":"WARNING",\
        "location":"unidad 1","issue":"Falta un ejemplo resuelto","correction":null}]}
        ```"""


@pytest.mark.asyncio
async def test_semantic_critic_parses_json_and_can_only_downgrade() -> None:
    deterministic = CurriculumCritic().finalize(
        request(),
        draft(chunk_ids=["doc-1:chunk-1"]),
        evidence(),
    ).curriculum
    semantic = SemanticCurriculumCritic(FakeSemanticModel())  # type: ignore[arg-type]

    report = await semantic.audit(deterministic, evidence())
    downgraded = semantic.apply_downgrade(deterministic, report)
    attempted_upgrade = semantic.apply_downgrade(
        downgraded,
        report.model_copy(update={"verdict": GroundingStatus.SUPPORTED}),
    )

    assert report.findings[0].location == "unidad 1"
    assert downgraded.grounding_status is GroundingStatus.PARTIALLY_SUPPORTED
    assert attempted_upgrade.grounding_status is GroundingStatus.PARTIALLY_SUPPORTED
