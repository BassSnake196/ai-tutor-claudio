from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.library import router
from app.services.curriculum_library import CurriculumLibrary


def app_with_library() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.curriculum_library = CurriculumLibrary()
    return app


def draft_payload(audited: bool = False) -> dict[str, object]:
    curriculum: dict[str, object] = {
        "schema_version": "1.0",
        "topic_title": "Álgebra",
        "target_level": "Secundaria",
        "pedagogical_approach": "Problemas",
        "learning_objectives": ["Resolver ecuaciones"],
        "syllabus_units": [{
            "unit_number": 1,
            "unit_name": "Ecuaciones",
            "estimated_hours": 4,
            "subtopics": ["Igualdad"],
            "didactic_explanation": "Balanza algebraica",
        }],
    }
    if audited:
        curriculum["grounding_status"] = "UNSUPPORTED"
        curriculum["syllabus_units"][0]["citations"] = []  # type: ignore[index]
    return {"title": "Álgebra", "curriculum": curriculum}


def headers(tenant: str = "tenant-a", user: str = "user-a") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-User-ID": user}


def test_library_api_scopes_records_and_supports_optimistic_update() -> None:
    with TestClient(app_with_library()) as client:
        response = client.post("/v1/library/curricula", json=draft_payload(), headers=headers())
        assert response.status_code == 201
        record_id = response.json()["id"]
        assert client.get("/v1/library/curricula", headers=headers("tenant-a", "user-b")).json()["total"] == 0
        assert client.get(f"/v1/library/curricula/{record_id}", headers=headers("tenant-b", "user-a")).status_code == 403
        assert client.patch(
            f"/v1/library/curricula/{record_id}",
            json={"title": "Álgebra I", "expected_version": 1},
            headers=headers(),
        ).json()["version"] == 2
        assert client.patch(
            f"/v1/library/curricula/{record_id}",
            json={"title": "stale", "expected_version": 1},
            headers=headers(),
        ).status_code == 409
        assert client.delete(f"/v1/library/curricula/{record_id}", headers=headers()).status_code == 204
        assert client.get(f"/v1/library/curricula/{record_id}", headers=headers()).status_code == 404
        archived = client.get(
            f"/v1/library/curricula/{record_id}?include_archived=true", headers=headers()
        )
        assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"


def test_library_api_requires_scope_headers_and_exports_only_audited_curricula() -> None:
    with TestClient(app_with_library()) as client:
        assert client.get("/v1/library/curricula").status_code == 401
        draft = client.post("/v1/library/curricula", json=draft_payload(), headers=headers()).json()
        assert client.get(f"/v1/library/curricula/{draft['id']}/export", headers=headers()).status_code == 422
        audited = client.post("/v1/library/curricula", json=draft_payload(audited=True), headers=headers()).json()
        exported = client.get(f"/v1/library/curricula/{audited['id']}/export?format=markdown", headers=headers())
        assert exported.status_code == 200
        assert "# Álgebra" in exported.text
        assert "UNSUPPORTED" in exported.text
