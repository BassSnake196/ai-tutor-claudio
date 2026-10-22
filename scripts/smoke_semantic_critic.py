"""Run one local-only semantic critic smoke test against configured Ollama."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.critic_agent import SemanticCurriculumCritic  # noqa: E402
from app.ai.registry import ModelRegistry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.schemas.curriculum_schema import CurriculumResponse, SyllabusUnit  # noqa: E402
from app.schemas.sources import GroundingStatus  # noqa: E402


async def main() -> None:
    settings = get_settings()
    curriculum = CurriculumResponse(
        topic_title="Suma de fracciones",
        target_level="Secundaria",
        pedagogical_approach="Resolución de problemas",
        learning_objectives=["Resolver sumas de fracciones con distinto denominador."],
        syllabus_units=[
            SyllabusUnit(
                unit_number=1,
                unit_name="Denominador común",
                estimated_hours=1,
                subtopics=["Mínimo común múltiplo"],
                didactic_explanation="Se obtiene un denominador común antes de sumar.",
                practical_activities=["Resolver tres ejercicios en parejas."],
                learning_outcomes=["Suma fracciones con distinto denominador."],
                essential_concepts=["Fracciones equivalentes"],
                formative_assessment="Ticket de salida de dos reactivos.",
            )
        ],
        grounding_status=GroundingStatus.UNSUPPORTED,
    )
    critic = SemanticCurriculumCritic(ModelRegistry(settings).semantic_critic_llm())
    report = await critic.audit(curriculum, evidence=None)
    print(
        json.dumps(
            {
                "model": settings.ollama_model,
                "verdict": report.verdict.value,
                "findings": len(report.findings),
                "prompt_tokens": critic.last_usage.prompt_tokens,
                "output_tokens": critic.last_usage.output_tokens,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
