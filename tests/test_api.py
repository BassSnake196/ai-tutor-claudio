from fastapi.testclient import TestClient

from app.ai.orchestrator import TutorOrchestrator
from app.ai.registry import ModelRegistry
from app.core.config import get_settings
from app.main import create_app


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_source_query_abstains_without_indexed_documents() -> None:
    with TestClient(create_app()) as client:
        client.app.state.orchestrator = TutorOrchestrator(ModelRegistry(get_settings()), rag=None)
        response = client.post("/v1/tutor/query", json={"prompt": "¿Qué dice el documento?", "requires_sources": True})

    assert response.status_code == 200
    assert response.json()["grounding_status"] == "INSUFFICIENT_CONTEXT"
