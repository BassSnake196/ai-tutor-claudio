import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG_TESTS") != "1",
    reason="Requiere Ollama y Qdrant locales.",
)


def test_document_api_indexes_and_answers_with_citations() -> None:
    content = Path("tests/fixtures/pedagogy.txt").read_bytes()
    with TestClient(create_app()) as client:
        ingestion = client.post(
            "/v1/documents",
            files={"file": ("pedagogy.txt", content, "text/plain")},
            data={"source_id": "pedagogy-api-fixture"},
        )
        response = client.post(
            "/v1/tutor/query",
            json={
                "prompt": "¿Para qué sirve la evaluación formativa?",
                "requires_sources": True,
            },
        )

    assert ingestion.status_code == 201
    assert ingestion.json()["chunk_count"] >= 1
    assert response.status_code == 200
    assert response.json()["grounding_status"] == "PARTIALLY_SUPPORTED"
    assert response.json()["citations"]
