from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.interfaces.llm import LLMProviderError
from app.ai.curriculum_orchestrator import SelectedSourcesNotFoundError
from app.api.routes.curricula import router
from app.schemas.curriculum_schema import CurriculumResponse, SyllabusUnit
from app.schemas.responses import CurriculumGenerationResponse, CurriculumGenerationStatus
from app.schemas.source_resolution import SourcePolicy, SourceResolutionTrace
from app.schemas.sources import GroundingStatus


def completed_response() -> CurriculumGenerationResponse:
    curriculum = CurriculumResponse(
        topic_title="Álgebra",
        target_level="Secundaria",
        pedagogical_approach="Problemas",
        learning_objectives=["Resolver ecuaciones"],
        syllabus_units=[
            SyllabusUnit(
                unit_number=1,
                unit_name="Ecuaciones",
                estimated_hours=4,
                subtopics=["Igualdad"],
                didactic_explanation="Balanza algebraica",
            )
        ],
        grounding_status=GroundingStatus.UNSUPPORTED,
    )
    return CurriculumGenerationResponse(
        request_id="cur-test",
        status=CurriculumGenerationStatus.COMPLETED,
        curriculum=curriculum,
        grounding_status=GroundingStatus.UNSUPPORTED,
        source_trace=SourceResolutionTrace(
            policy=SourcePolicy.NO_SOURCES,
            stop_reason="Sin fuentes",
        ),
        latency_ms=1,
    )


def app_with(orchestrator: object) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.curriculum_orchestrator = orchestrator
    return app


def payload() -> dict[str, object]:
    return {
        "topic": "Álgebra",
        "target_level": "Secundaria",
        "duration_weeks": 2,
        "hours_per_week": 2,
        "source_policy": "NO_SOURCES",
    }


def test_curriculum_endpoint_returns_structured_envelope() -> None:
    class Stub:
        async def generate(self, _request):
            return completed_response()

    response = TestClient(app_with(Stub())).post("/v1/curricula", json=payload())

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["curriculum"]["topic_title"] == "Álgebra"


def test_curriculum_endpoint_maps_provider_failure_to_503() -> None:
    class Stub:
        async def generate(self, _request):
            raise LLMProviderError("Gemini temporalmente no disponible")

    response = TestClient(app_with(Stub())).post("/v1/curricula", json=payload())

    assert response.status_code == 503
    assert "temporalmente" in response.json()["detail"]


def test_curriculum_endpoint_rejects_incompatible_policy() -> None:
    bad = payload()
    bad["source_policy"] = "UPLOADED_ONLY"

    response = TestClient(app_with(object())).post("/v1/curricula", json=bad)

    assert response.status_code == 422


def test_curriculum_endpoint_returns_404_for_missing_selected_source() -> None:
    class Stub:
        async def generate(self, _request):
            raise SelectedSourcesNotFoundError(["missing-doc"])

    selected = payload()
    selected["source_policy"] = "UPLOADED_ONLY"
    selected["source_ids"] = ["missing-doc"]
    response = TestClient(app_with(Stub())).post("/v1/curricula", json=selected)

    assert response.status_code == 404
    assert "missing-doc" in response.json()["detail"]
