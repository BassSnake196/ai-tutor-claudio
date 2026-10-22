from fastapi import APIRouter, HTTPException, Request, status

from app.ai.curriculum_orchestrator import CurriculumOrchestrator, SelectedSourcesNotFoundError
from app.ai.interfaces.llm import LLMProviderError
from app.schemas.requests import CurriculumRequest
from app.schemas.responses import CurriculumGenerationResponse


router = APIRouter(prefix="/v1/curricula", tags=["curricula"])


@router.post("", response_model=CurriculumGenerationResponse)
async def generate_curriculum(
    payload: CurriculumRequest,
    request: Request,
) -> CurriculumGenerationResponse:
    orchestrator: CurriculumOrchestrator = request.app.state.curriculum_orchestrator
    try:
        return await orchestrator.generate(payload)
    except SelectedSourcesNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
