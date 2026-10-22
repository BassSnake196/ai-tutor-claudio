from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.documents import router
from app.rag.source_metadata import SourceRecord


class FakeCatalogRag:
    def __init__(self) -> None:
        self.source = SourceRecord(
            source_id="algebra",
            document_id="doc-algebra",
            library_id="default",
            course_id="matematicas",
            title="Álgebra",
            source_type="pdf",
            language="es",
            document_hash="document-hash",
            ingested_at="2026-08-27T00:00:00+00:00",
            status="ACTIVE",
            schema_version="2",
            chunk_count=3,
        )
        self.deleted: list[str] = []

    async def list_sources(self, **_: object) -> list[SourceRecord]:
        return [] if self.deleted else [self.source]

    async def get_source(self, source_id: str) -> SourceRecord | None:
        if source_id != self.source.source_id or source_id in self.deleted:
            return None
        return self.source

    async def delete_source(self, source_id: str) -> bool:
        if await self.get_source(source_id) is None:
            return False
        self.deleted.append(source_id)
        return True


def test_document_catalog_list_detail_delete_and_not_found() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.rag = FakeCatalogRag()

    with TestClient(app) as client:
        listing = client.get("/v1/documents")
        detail = client.get("/v1/documents/algebra")
        deletion = client.delete("/v1/documents/algebra")
        missing = client.get("/v1/documents/algebra")

    assert listing.status_code == 200
    assert listing.json()[0]["chunk_count"] == 3
    assert "storage_paths" not in listing.json()[0]
    assert detail.status_code == 200
    assert deletion.json() == {
        "source_id": "algebra",
        "deleted": True,
        "deleted_chunks": 3,
        "deleted_files": 0,
    }
    assert missing.status_code == 404
