from fastapi import APIRouter, Request

from app.ai.orchestrator import TutorOrchestrator
from app.core.security import sanitize_prompt
from app.schemas.requests import TutorQueryRequest
from app.schemas.responses import TutorResponse


router = APIRouter(prefix="/v1/tutor", tags=["tutor"])


@router.post("/query", response_model=TutorResponse)
async def query_tutor(payload: TutorQueryRequest, request: Request) -> TutorResponse:
    sanitized_payload = payload.model_copy(update={"prompt": sanitize_prompt(payload.prompt)})
    orchestrator: TutorOrchestrator = request.app.state.orchestrator
    return await orchestrator.answer(sanitized_payload)
