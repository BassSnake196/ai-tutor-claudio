from types import SimpleNamespace

import pytest

from app.ai.curriculum_orchestrator import CurriculumOrchestrator
from app.ai.interfaces.llm import (
    LLMProviderError,
    StructuredGeneration,
    TextGeneration,
    TokenUsage,
)
from app.schemas.curriculum_schema import CurriculumDraft, CurriculumUnitDraft
from app.schemas.requests import CurriculumRequest
from app.schemas.responses import CurriculumGenerationStatus
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


def curriculum_request(policy: SourcePolicy = SourcePolicy.LOCAL_FIRST) -> CurriculumRequest:
    return CurriculumRequest(
        topic="Álgebra",
        target_level="Secundaria",
        duration_weeks=2,
        hours_per_week=2,
        source_policy=policy,
    )


def coverage(sufficient: bool) -> CoverageReport:
    categories = list(ResearchCategory)[:4]
    return CoverageReport(
        required_categories=categories,
        covered_categories=categories if sufficient else [ResearchCategory.CONCEPTS],
        missing_categories=[] if sufficient else categories[1:],
        score=1 if sufficient else 0.25,
        sufficient=sufficient,
        unique_chunks=4 if sufficient else 1,
    )


def bundle(sufficient: bool = True) -> EvidenceBundle:
    report = coverage(sufficient)
    chunks = []
    if sufficient:
        chunks = [
            EvidenceChunk(
                chunk_id="doc-1:chunk-1",
                content="Una ecuación expresa una igualdad.",
                score=0.9,
                category=ResearchCategory.CONCEPTS,
                stage=ResolutionStage.LOCAL_LIBRARY,
                metadata=SourceMetadata(source_id="doc-1", chunk_index=0),
                fragment_reference="doc-1#chunk=doc-1:chunk-1",
            )
        ]
    return EvidenceBundle(
        chunks=chunks,
        coverage=report,
        trace=SourceResolutionTrace(
            policy=SourcePolicy.LOCAL_FIRST,
            final_coverage=report,
            stop_reason="done",
        ),
    )


def draft(hours: float = 4, *, explanation: str = "Base") -> CurriculumDraft:
    return CurriculumDraft(
        topic_title="Álgebra",
        target_level="Secundaria",
        pedagogical_approach="Problemas",
        learning_objectives=["Resolver ecuaciones"],
        syllabus_units=[
            CurriculumUnitDraft(
                unit_number=1,
                unit_name="Ecuaciones",
                estimated_hours=hours,
                subtopics=["Igualdad"],
                didactic_explanation=explanation,
                practical_activities=["Balanza"],
                learning_outcomes=["Resolver ecuaciones"],
                essential_concepts=["Igualdad"],
                formative_assessment="Ticket",
                evidence_chunk_ids=["doc-1:chunk-1"],
            )
        ],
    )


class FakeResolver:
    def __init__(self, result: EvidenceBundle) -> None:
        self.result = result

    async def resolve(self, request: CurriculumRequest) -> EvidenceBundle:
        self.result.trace.policy = request.source_policy
        return self.result


class SequenceModel:
    def __init__(self, outputs: list[CurriculumDraft | Exception]) -> None:
        self.outputs = outputs
        self.calls = 0

    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        return "unused"

    async def generate_structured(self, prompt: str, **_kwargs):
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return StructuredGeneration(
            value=output,
            model="fake-flash",
            usage=TokenUsage(prompt_tokens=100, output_tokens=50, total_tokens=150),
        )


class SemanticModel:
    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        return "unused"

    async def generate_with_usage(
        self, prompt: str, *, system_instruction: str | None = None
    ) -> TextGeneration:
        return TextGeneration(
            text='{"verdict":"SUPPORTED","findings":[]}',
            model="fake-local",
            usage=TokenUsage(prompt_tokens=20, output_tokens=5, total_tokens=25),
        )


@pytest.mark.asyncio
async def test_insufficient_evidence_stops_before_spending_generation_tokens() -> None:
    model = SequenceModel([draft()])
    orchestrator = CurriculumOrchestrator(
        SimpleNamespace(cloud_llm=lambda: model),  # type: ignore[arg-type]
        FakeResolver(bundle(False)),  # type: ignore[arg-type]
    )

    result = await orchestrator.generate(curriculum_request())

    assert result.status is CurriculumGenerationStatus.INSUFFICIENT_CONTEXT
    assert result.curriculum is None
    assert result.token_usage.total_tokens == 0
    assert model.calls == 0


@pytest.mark.asyncio
async def test_completed_curriculum_tracks_both_agents_and_tokens() -> None:
    model = SequenceModel([draft(), draft(explanation="Enriquecida")])
    orchestrator = CurriculumOrchestrator(
        SimpleNamespace(cloud_llm=lambda: model),  # type: ignore[arg-type]
        FakeResolver(bundle()),  # type: ignore[arg-type]
    )

    result = await orchestrator.generate(curriculum_request())

    assert result.status is CurriculumGenerationStatus.COMPLETED
    assert result.curriculum is not None
    assert result.curriculum.syllabus_units[0].didactic_explanation == "Enriquecida"
    assert result.curriculum.grounding_status is GroundingStatus.SUPPORTED
    assert result.token_usage.total_tokens == 300
    assert [usage.role for usage in result.models_used] == [
        "curriculum_architect",
        "teaching_enrichment",
    ]


@pytest.mark.asyncio
async def test_teaching_failure_keeps_valid_architecture() -> None:
    model = SequenceModel([draft(), LLMProviderError("temporary")])
    orchestrator = CurriculumOrchestrator(
        SimpleNamespace(cloud_llm=lambda: model),  # type: ignore[arg-type]
        FakeResolver(bundle()),  # type: ignore[arg-type]
    )

    result = await orchestrator.generate(curriculum_request())

    assert result.status is CurriculumGenerationStatus.COMPLETED
    assert result.curriculum is not None
    assert len(result.models_used) == 1
    assert any("enriquecimiento" in warning.casefold() for warning in result.warnings)


@pytest.mark.asyncio
async def test_architecture_hours_are_normalized_before_teaching() -> None:
    model = SequenceModel([draft(hours=10), draft(hours=4)])
    orchestrator = CurriculumOrchestrator(
        SimpleNamespace(cloud_llm=lambda: model),  # type: ignore[arg-type]
        FakeResolver(bundle()),  # type: ignore[arg-type]
    )

    result = await orchestrator.generate(curriculum_request())

    assert result.curriculum is not None
    assert sum(unit.estimated_hours for unit in result.curriculum.syllabus_units) == 4
    assert any("normalizó" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_semantic_audit_adds_local_usage_to_total() -> None:
    model = SequenceModel([draft(), draft(explanation="Enriquecida")])
    registry = SimpleNamespace(
        cloud_llm=lambda: model,
        semantic_critic_llm=lambda: SemanticModel(),
        local_model_name="fake-local",
    )
    orchestrator = CurriculumOrchestrator(
        registry,  # type: ignore[arg-type]
        FakeResolver(bundle()),  # type: ignore[arg-type]
        semantic_audit_enabled=True,
    )

    result = await orchestrator.generate(curriculum_request())

    assert [usage.role for usage in result.models_used] == [
        "curriculum_architect",
        "teaching_enrichment",
        "semantic_critic",
    ]
    assert result.models_used[-1].token_usage.total_tokens == 25
    assert result.token_usage.total_tokens == 325
