import pytest

from app.agents.prompts import (
    CRITIC_SYSTEM_PROMPT,
    CURRICULUM_ARCHITECT_SYSTEM_PROMPT,
    INGESTOR_SYSTEM_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    TEACHING_SYSTEM_PROMPT,
)
from app.ai.orchestrator import TutorOrchestrator
from app.schemas.requests import TutorQueryRequest


class SpyModel:
    def __init__(self) -> None:
        self.system_instruction: str | None = None

    async def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        self.system_instruction = system_instruction
        return "contenido generado"


class SpyRegistry:
    def __init__(self) -> None:
        self.cloud = SpyModel()
        self.local = SpyModel()

    def cloud_llm(self) -> SpyModel:
        return self.cloud

    def local_llm(self) -> SpyModel:
        return self.local


def test_all_specialized_prompts_define_role_process_and_limits() -> None:
    prompts = (
        ROUTER_SYSTEM_PROMPT,
        RESEARCH_SYSTEM_PROMPT,
        INGESTOR_SYSTEM_PROMPT,
        CURRICULUM_ARCHITECT_SYSTEM_PROMPT,
        TEACHING_SYSTEM_PROMPT,
        CRITIC_SYSTEM_PROMPT,
    )

    assert all(len(prompt) > 500 for prompt in prompts)
    assert "inventes autores" in RESEARCH_SYSTEM_PROMPT.casefold()
    assert "alineación constructiva" in CURRICULUM_ARCHITECT_SYSTEM_PROMPT.casefold()
    assert "taxonomía de bloom" in CURRICULUM_ARCHITECT_SYSTEM_PROMPT.casefold()
    assert "SUPPORTED" in CRITIC_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_curriculum_request_uses_curriculum_architect_prompt() -> None:
    registry = SpyRegistry()
    orchestrator = TutorOrchestrator(registry=registry)  # type: ignore[arg-type]

    response = await orchestrator.answer(
        TutorQueryRequest(
            prompt="Crea un temario de álgebra de cuatro semanas.",
            requires_sources=False,
        )
    )

    assert response.route == "CLOUD"
    assert registry.cloud.system_instruction == CURRICULUM_ARCHITECT_SYSTEM_PROMPT
