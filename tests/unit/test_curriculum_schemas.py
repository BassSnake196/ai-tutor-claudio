import pytest
from pydantic import ValidationError

from app.schemas.curriculum_schema import (
    CurriculumDraft,
    CurriculumResponse,
    CurriculumUnitDraft,
    EvaluationQuestion,
    SyllabusUnit,
)
from app.schemas.requests import CurriculumRequest
from app.schemas.responses import (
    CurriculumGenerationResponse,
    CurriculumGenerationStatus,
    ModelUsage,
    StageLatency,
    TokenUsage,
)
from app.schemas.source_resolution import (
    CoverageReport,
    EvidenceBundle,
    EvidenceChunk,
    ResearchCategory,
    ResolutionStage,
    ResolutionStageTrace,
    SourceFilters,
    SourcePolicy,
    SourceResolutionTrace,
)
from app.schemas.sources import Citation, GroundingStatus, SourceMetadata, SourceType


def minimal_request(**overrides: object) -> CurriculumRequest:
    values: dict[str, object] = {
        "topic": "Álgebra básica",
        "target_level": "Secundaria",
        "duration_weeks": 4,
        "hours_per_week": 3,
    }
    values.update(overrides)
    return CurriculumRequest(**values)


def coverage(*, sufficient: bool = True) -> CoverageReport:
    return CoverageReport(
        required_categories=[
            ResearchCategory.CONCEPTS,
            ResearchCategory.PROGRESSION,
            ResearchCategory.DIDACTICS,
            ResearchCategory.ASSESSMENT,
        ],
        covered_categories=(
            [
                ResearchCategory.CONCEPTS,
                ResearchCategory.PROGRESSION,
                ResearchCategory.ASSESSMENT,
            ]
            if sufficient
            else [ResearchCategory.CONCEPTS]
        ),
        missing_categories=(
            [ResearchCategory.DIDACTICS]
            if sufficient
            else [
                ResearchCategory.PROGRESSION,
                ResearchCategory.DIDACTICS,
                ResearchCategory.ASSESSMENT,
            ]
        ),
        score=0.75 if sufficient else 0.25,
        sufficient=sufficient,
        unique_chunks=4 if sufficient else 1,
    )


def trace(*, policy: SourcePolicy = SourcePolicy.LOCAL_FIRST) -> SourceResolutionTrace:
    final_coverage = coverage()
    return SourceResolutionTrace(
        policy=policy,
        stages=[
            ResolutionStageTrace(
                stage=ResolutionStage.SELECTED,
                queries=["conceptos de álgebra"],
                filters=SourceFilters(source_ids=["doc-1"]),
                retrieved_count=4,
                accepted_count=4,
                coverage_after_stage=final_coverage,
                latency_ms=12,
                stop_reason="selected evidence was sufficient",
            )
        ],
        final_coverage=final_coverage,
        stop_reason="coverage threshold reached",
    )


def unit(unit_type: type[CurriculumUnitDraft] = SyllabusUnit) -> CurriculumUnitDraft:
    values: dict[str, object] = {
        "unit_number": 1,
        "unit_name": "Ecuaciones lineales",
        "estimated_hours": 12,
        "subtopics": ["Variables", "Igualdad"],
        "didactic_explanation": "Del balance concreto a la representación simbólica.",
        "practical_activities": ["Resolver una balanza dibujada"],
        "evaluation_questions": [
            EvaluationQuestion(
                question="¿Qué operación conserva la igualdad?",
                expected_answer="Aplicar la misma operación en ambos miembros.",
            )
        ],
        "prerequisites": ["Operaciones con enteros"],
        "learning_outcomes": ["Resolver ecuaciones lineales"],
        "essential_concepts": ["Variable", "equivalencia"],
        "common_misconceptions": ["Cambiar de lado cambia el signo automáticamente"],
        "guided_activity": "Modelado con una balanza.",
        "independent_activity": "Problemas graduados.",
        "formative_assessment": "Ticket de salida.",
        "evidence_of_learning": ["Procedimiento escrito"],
    }
    if issubclass(unit_type, SyllabusUnit):
        values["citations"] = [
            Citation(source_id="doc-1", fragment_reference="doc-1#chunk-1")
        ]
    return unit_type(**values)


def curriculum() -> CurriculumResponse:
    return CurriculumResponse(
        topic_title="Álgebra básica",
        target_level="Secundaria",
        pedagogical_approach="Resolución de problemas",
        learning_objectives=["Resolver ecuaciones lineales"],
        syllabus_units=[unit()],
        grounding_status=GroundingStatus.SUPPORTED,
    )


def test_minimal_curriculum_request_has_safe_defaults() -> None:
    request = minimal_request()

    assert request.source_policy is SourcePolicy.LOCAL_FIRST
    assert request.library_id == "default"
    assert request.source_ids == []
    assert request.prior_knowledge == []


def test_request_strips_text_and_deduplicates_sources_preserving_order() -> None:
    request = minimal_request(
        topic="  Álgebra  ", source_ids=["doc-b", "doc-a", "doc-b"]
    )

    assert request.topic == "Álgebra"
    assert request.source_ids == ["doc-b", "doc-a"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_weeks", 0),
        ("duration_weeks", 53),
        ("hours_per_week", 0),
        ("hours_per_week", 41),
        ("topic", "   "),
        ("target_level", ""),
        ("source_ids", ["id with spaces"]),
        ("library_id", "../library"),
    ],
)
def test_request_rejects_invalid_limits_and_identifiers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        minimal_request(**{field: value})


def test_uploaded_only_requires_selected_sources() -> None:
    with pytest.raises(ValidationError, match="requires at least one source_id"):
        minimal_request(source_policy=SourcePolicy.UPLOADED_ONLY)


def test_no_sources_rejects_selected_sources() -> None:
    with pytest.raises(ValidationError, match="does not accept source_ids"):
        minimal_request(source_policy=SourcePolicy.NO_SOURCES, source_ids=["doc-1"])


def test_source_policy_permissions_are_unambiguous() -> None:
    assert not SourcePolicy.UPLOADED_ONLY.allows_local_expansion
    assert SourcePolicy.LOCAL_FIRST.allows_local_expansion
    assert SourcePolicy.EXTERNAL_ALLOWED.allows_local_expansion
    assert SourcePolicy.EXTERNAL_ALLOWED.allows_external_search
    assert not SourcePolicy.NO_SOURCES.allows_external_search


def test_unknown_request_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        minimal_request(typo_field="value")


def test_draft_has_no_grounding_claim_or_unit_citations() -> None:
    draft = CurriculumDraft(
        topic_title="Álgebra básica",
        target_level="Secundaria",
        pedagogical_approach="Resolución de problemas",
        learning_objectives=["Resolver ecuaciones"],
        syllabus_units=[unit(CurriculumUnitDraft)],
    )
    serialized = draft.model_dump()

    assert "grounding_status" not in serialized
    assert "citations" not in serialized["syllabus_units"][0]


def test_original_curriculum_response_shape_remains_usable() -> None:
    response = CurriculumResponse(
        topic_title="Fracciones",
        target_level="Primaria",
        pedagogical_approach="Concreto-pictórico-abstracto",
        learning_objectives=["Comparar fracciones"],
        syllabus_units=[
            SyllabusUnit(
                unit_number=1,
                unit_name="Representación",
                estimated_hours=2,
                subtopics=["Partes de un todo"],
                didactic_explanation="Usar material manipulable.",
            )
        ],
        grounding_status=GroundingStatus.UNSUPPORTED,
    )

    assert response.schema_version == "1.0"
    assert response.syllabus_units[0].prerequisites == []


def test_evidence_bundle_serializes_both_hierarchical_stages() -> None:
    final_coverage = coverage()
    stage_traces = [
        ResolutionStageTrace(
            stage=ResolutionStage.SELECTED,
            filters=SourceFilters(source_ids=["doc-1"]),
            retrieved_count=1,
            accepted_count=1,
        ),
        ResolutionStageTrace(
            stage=ResolutionStage.LOCAL_LIBRARY,
            filters=SourceFilters(
                excluded_source_ids=["doc-1"], library_id="default"
            ),
            retrieved_count=3,
            accepted_count=3,
        ),
    ]
    resolution_trace = SourceResolutionTrace(
        policy=SourcePolicy.LOCAL_FIRST,
        stages=stage_traces,
        final_coverage=final_coverage,
        stop_reason="local expansion completed coverage",
    )
    evidence = EvidenceBundle(
        chunks=[
            EvidenceChunk(
                chunk_id="chunk-1",
                content="Una ecuación expresa una igualdad.",
                score=0.82,
                category=ResearchCategory.CONCEPTS,
                stage=ResolutionStage.SELECTED,
                metadata=SourceMetadata(
                    source_id="doc-1",
                    chunk_index=0,
                    source_type=SourceType.PDF,
                ),
                fragment_reference="doc-1#chunk-1",
            )
        ],
        coverage=final_coverage,
        trace=resolution_trace,
    )

    payload = evidence.model_dump(mode="json")
    assert [item["stage"] for item in payload["trace"]["stages"]] == [
        "SELECTED",
        "LOCAL_LIBRARY",
    ]
    assert payload["chunks"][0]["metadata"]["source_type"] == "pdf"


def test_evidence_bundle_rejects_more_than_twelve_chunks() -> None:
    chunk = EvidenceChunk(
        chunk_id="chunk",
        content="Contenido",
        score=0.5,
        category=ResearchCategory.CONCEPTS,
        stage=ResolutionStage.SELECTED,
        metadata=SourceMetadata(source_id="doc", chunk_index=0),
        fragment_reference="doc#chunk",
    )
    with pytest.raises(ValidationError):
        EvidenceBundle(
            chunks=[chunk.model_copy(update={"chunk_id": f"chunk-{index}"}) for index in range(13)],
            coverage=coverage(),
            trace=trace(),
        )


def test_completed_generation_envelope_tracks_models_and_latencies() -> None:
    response = CurriculumGenerationResponse(
        request_id="req-123",
        status=CurriculumGenerationStatus.COMPLETED,
        curriculum=curriculum(),
        grounding_status=GroundingStatus.SUPPORTED,
        source_trace=trace(),
        models_used=[
            ModelUsage(
                provider="ollama",
                model="nomic-embed-text",
                role="embedding",
                calls=5,
                token_usage=TokenUsage(
                    prompt_tokens=200, output_tokens=0, total_tokens=200
                ),
            ),
            ModelUsage(
                provider="google",
                model="gemini-3.5-flash",
                role="curriculum",
                token_usage=TokenUsage(
                    prompt_tokens=500, output_tokens=300, total_tokens=800
                ),
            ),
        ],
        token_usage=TokenUsage(prompt_tokens=700, output_tokens=300, total_tokens=1000),
        latency_ms=140,
        stage_latencies=[
            StageLatency(
                stage="retrieval",
                latency_ms=40,
                token_usage=TokenUsage(
                    prompt_tokens=200, output_tokens=0, total_tokens=200
                ),
            ),
            StageLatency(
                stage="generation",
                latency_ms=100,
                token_usage=TokenUsage(
                    prompt_tokens=500, output_tokens=300, total_tokens=800
                ),
            ),
        ],
    )

    payload = response.model_dump(mode="json")
    assert payload["status"] == "COMPLETED"
    assert payload["models_used"][1]["model"] == "gemini-3.5-flash"
    assert payload["models_used"][0]["calls"] == 5
    assert payload["token_usage"]["total_tokens"] == 1000
    assert payload["stage_latencies"][0]["token_usage"]["total_tokens"] == 200


def test_completed_generation_requires_curriculum() -> None:
    with pytest.raises(ValidationError, match="COMPLETED requires a curriculum"):
        CurriculumGenerationResponse(
            request_id="req-1",
            status=CurriculumGenerationStatus.COMPLETED,
            grounding_status=GroundingStatus.SUPPORTED,
            source_trace=trace(),
            latency_ms=1,
        )


def test_insufficient_context_envelope_is_a_valid_domain_result() -> None:
    response = CurriculumGenerationResponse(
        request_id="req-2",
        status=CurriculumGenerationStatus.INSUFFICIENT_CONTEXT,
        grounding_status=GroundingStatus.INSUFFICIENT_CONTEXT,
        source_trace=trace(policy=SourcePolicy.UPLOADED_ONLY),
        warnings=["No se recuperó evidencia suficiente."],
        latency_ms=20,
    )

    assert response.curriculum is None


def test_non_completed_status_rejects_curriculum_and_mismatched_grounding() -> None:
    with pytest.raises(ValidationError, match="must not include a curriculum"):
        CurriculumGenerationResponse(
            request_id="req-3",
            status=CurriculumGenerationStatus.PROVIDER_UNAVAILABLE,
            curriculum=curriculum(),
            grounding_status=GroundingStatus.UNSUPPORTED,
            source_trace=trace(),
            latency_ms=20,
        )

    with pytest.raises(ValidationError, match="matching grounding_status"):
        CurriculumGenerationResponse(
            request_id="req-4",
            status=CurriculumGenerationStatus.INSUFFICIENT_CONTEXT,
            grounding_status=GroundingStatus.PARTIALLY_SUPPORTED,
            source_trace=trace(),
            latency_ms=20,
        )


def test_nested_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceFilters(library_id="default", unrestricted=True)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StageLatency(stage="generation", latency_ms=1, secret="do-not-log")


def test_token_usage_requires_consistent_total() -> None:
    with pytest.raises(ValidationError, match="total_tokens"):
        TokenUsage(prompt_tokens=10, output_tokens=5, total_tokens=99)


def test_citation_rejects_inverted_timestamp_range() -> None:
    with pytest.raises(ValidationError, match="timestamp_end"):
        Citation(
            source_id="video-1",
            fragment_reference="00:20-00:10",
            timestamp_start=20,
            timestamp_end=10,
        )
