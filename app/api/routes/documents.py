import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from app.rag.documents import UnsupportedDocumentError
from app.rag.service import DuplicateDocumentError, RagService, SourceIdConflictError
from app.rag.source_metadata import DEFAULT_LIBRARY_ID
from app.schemas.documents import DocumentIngestionResponse, DocumentSearchRequest, DocumentSearchResult


router = APIRouter(prefix="/v1/documents", tags=["documents"])
DATA_DIRECTORY = Path("data/raw_documents")
EXTERNAL_MEDIA_DIRECTORY = Path("data/videos_audio")
ALLOWED_SUFFIXES = {".txt", ".pdf", ".docx"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


@router.post("", response_model=DocumentIngestionResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    source_id: str = Form(..., min_length=1, max_length=200),
    library_id: str = Form(default=DEFAULT_LIBRARY_ID, min_length=1, max_length=200),
    course_id: str | None = Form(default=None, min_length=1, max_length=200),
    language: str = Form(default="es", min_length=2, max_length=16),
) -> DocumentIngestionResponse:
    suffix = Path(file.filename or "").suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Solo se permiten archivos TXT, PDF y DOCX.")

    safe_source_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", source_id)
    stored_path = DATA_DIRECTORY / f"{safe_source_id}-{uuid4().hex}{suffix}"
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="El documento supera el límite de 20 MB.")

    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)
    rag: RagService = request.app.state.rag
    try:
        document = await rag.index_document(
            stored_path,
            source_id=source_id,
            library_id=library_id,
            course_id=course_id,
            language=language,
        )
    except (DuplicateDocumentError, SourceIdConflictError) as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, UnsupportedDocumentError) as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise

    if document.already_indexed:
        stored_path.unlink(missing_ok=True)

    return DocumentIngestionResponse(
        source_id=document.source_id,
        title=document.title,
        source_type=document.source_type,
        chunk_count=len(document.chunks),
    )


@router.post("/search", response_model=list[DocumentSearchResult])
async def search_documents(payload: DocumentSearchRequest, request: Request) -> list[DocumentSearchResult]:
    rag: RagService = request.app.state.rag
    results = await rag.search(payload.query, limit=payload.limit)
    return [
        DocumentSearchResult(
            chunk_id=result.chunk_id,
            content=result.content,
            score=result.score,
            metadata=result.metadata,
        )
        for result in results
    ]


@router.get("")
async def list_documents(
    request: Request,
    library_id: str | None = Query(default=None, min_length=1, max_length=200),
    course_id: str | None = Query(default=None, min_length=1, max_length=200),
    document_status: str | None = Query(default=None, min_length=1, max_length=50),
) -> list[dict[str, Any]]:
    rag: RagService = request.app.state.rag
    sources = await rag.list_sources(
        library_id=library_id,
        course_id=course_id,
        status=document_status,
    )
    return [source.public_dict() for source in sources]


@router.get("/{source_id}")
async def get_document(source_id: str, request: Request) -> dict[str, Any]:
    rag: RagService = request.app.state.rag
    source = await rag.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="La fuente solicitada no existe.")
    return source.public_dict()


@router.delete("/{source_id}")
async def delete_document(source_id: str, request: Request) -> dict[str, Any]:
    rag: RagService = request.app.state.rag
    source = await rag.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="La fuente solicitada no existe.")

    deleted = await rag.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="La fuente solicitada no existe.")
    deleted_files = _delete_owned_files(source.storage_paths)
    return {
        "source_id": source_id,
        "deleted": True,
        "deleted_chunks": source.chunk_count,
        "deleted_files": deleted_files,
    }


def _delete_owned_files(storage_paths: tuple[str, ...]) -> int:
    """Delete only exact files located under this application's raw-document directory."""
    roots = (DATA_DIRECTORY.resolve(), EXTERNAL_MEDIA_DIRECTORY.resolve())
    deleted = 0
    for raw_path in storage_paths:
        candidate = Path(raw_path).resolve()
        if not any(candidate.is_relative_to(root) for root in roots) or not candidate.is_file():
            continue
        candidate.unlink()
        deleted += 1
    return deleted
