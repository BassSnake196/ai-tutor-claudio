"""Teacher-facing saved curriculum library and deterministic exports."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.core.tenant_context import TenantContext
from app.schemas.library import (
    CurriculumLibraryCreateRequest,
    CurriculumLibraryListResponse,
    CurriculumLibraryRecord,
    CurriculumLibraryUpdateRequest,
)
from app.services.curriculum_export import render_curriculum_json, render_curriculum_markdown
from app.services.curriculum_library import (
    CurriculumLibrary,
    CurriculumLibraryNotFoundError,
    CurriculumLibraryOwnershipError,
    CurriculumLibraryVersionConflictError,
)


router = APIRouter(prefix="/v1/library/curricula", tags=["teacher-library"])


def _context(tenant_id: str | None, user_id: str | None) -> TenantContext:
    try:
        return TenantContext.from_headers(tenant_id, user_id)
    except ValueError as exc:
        # These headers are an explicit development boundary, not authentication.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _library(request: Request) -> CurriculumLibrary:
    app = request.app
    library = getattr(getattr(app, "state", None), "curriculum_library", None)
    if library is None:
        raise HTTPException(status_code=503, detail="La biblioteca curricular no está disponible.")
    return library


@router.post("", response_model=CurriculumLibraryRecord, status_code=status.HTTP_201_CREATED)
async def create_curriculum(
    payload: CurriculumLibraryCreateRequest,
    request: Request,
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> CurriculumLibraryRecord:
    context = _context(x_tenant_id, x_user_id)
    return _library(request).create(context.tenant_id, context.user_id, payload)


@router.get("", response_model=CurriculumLibraryListResponse)
async def list_curricula(
    request: Request,
    include_archived: bool = Query(default=False),
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> CurriculumLibraryListResponse:
    context = _context(x_tenant_id, x_user_id)
    return _library(request).list(context.tenant_id, context.user_id, include_archived=include_archived)


@router.get("/{curriculum_id}", response_model=CurriculumLibraryRecord)
async def get_curriculum(
    curriculum_id: str,
    request: Request,
    include_archived: bool = Query(default=False),
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> CurriculumLibraryRecord:
    context = _context(x_tenant_id, x_user_id)
    try:
        return _library(request).get(curriculum_id, context.tenant_id, context.user_id, include_archived=include_archived)
    except CurriculumLibraryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="El currículo no existe.") from exc
    except CurriculumLibraryOwnershipError as exc:
        raise HTTPException(status_code=403, detail="No tienes acceso a este currículo.") from exc


@router.patch("/{curriculum_id}", response_model=CurriculumLibraryRecord)
async def update_curriculum(
    curriculum_id: str,
    payload: CurriculumLibraryUpdateRequest,
    request: Request,
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> CurriculumLibraryRecord:
    context = _context(x_tenant_id, x_user_id)
    try:
        return _library(request).update(curriculum_id, context.tenant_id, context.user_id, payload)
    except CurriculumLibraryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="El currículo no existe.") from exc
    except CurriculumLibraryOwnershipError as exc:
        raise HTTPException(status_code=403, detail="No tienes acceso a este currículo.") from exc
    except CurriculumLibraryVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{curriculum_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_curriculum(
    curriculum_id: str,
    request: Request,
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Response:
    context = _context(x_tenant_id, x_user_id)
    try:
        _library(request).delete(curriculum_id, context.tenant_id, context.user_id)
    except CurriculumLibraryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="El currículo no existe.") from exc
    except CurriculumLibraryOwnershipError as exc:
        raise HTTPException(status_code=403, detail="No tienes acceso a este currículo.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{curriculum_id}/export", response_class=PlainTextResponse)
async def export_curriculum(
    curriculum_id: str,
    request: Request,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> PlainTextResponse:
    context = _context(x_tenant_id, x_user_id)
    try:
        record = _library(request).get(curriculum_id, context.tenant_id, context.user_id)
    except CurriculumLibraryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="El currículo no existe.") from exc
    except CurriculumLibraryOwnershipError as exc:
        raise HTTPException(status_code=403, detail="No tienes acceso a este currículo.") from exc
    try:
        if format == "json":
            content = render_curriculum_json(record.curriculum)
            media_type = "application/json"
        else:
            content = render_curriculum_markdown(record.curriculum)
            media_type = "text/markdown"
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Sólo se pueden exportar currículos auditados.") from exc
    return PlainTextResponse(content=content, media_type=media_type)
