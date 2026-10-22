from pathlib import Path

from app.rag.ingestion import DocumentIngestionService


def test_ingestion_extracts_and_chunks_a_text_document(tmp_path: Path) -> None:
    document = tmp_path / "fundamentos.txt"
    document.write_text("Aprendizaje activo. " * 100, encoding="utf-8")

    ingested = DocumentIngestionService().ingest(document, source_id="doc-fundamentos", chunk_size=100)

    assert ingested.title == "fundamentos"
    assert ingested.source_type == "txt"
    assert len(ingested.chunks) > 1
