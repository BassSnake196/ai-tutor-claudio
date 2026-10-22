import json
from pathlib import Path

import pytest

from scripts.eval.generate_curriculum_responses import load_tasks, run_eval, task_to_request
from app.agents.prompts import CURRICULUM_ARCHITECT_OBSERVABLE_V2_PROMPT
from app.ai.interfaces.llm import StructuredGeneration, TokenUsage
from app.schemas.curriculum_schema import CurriculumDraft, CurriculumUnitDraft


def test_loader_defaults_to_no_sources_and_blocks_test() -> None:
    tasks = load_tasks(Path("data/eval/curriculum/tasks.v1.jsonl"))
    assert tasks and all(task["policy"] == "NO_SOURCES" for task in tasks)
    assert all(task["split"] != "test" for task in tasks)


def test_task_maps_to_curriculum_request() -> None:
    task = load_tasks(Path("data/eval/curriculum/tasks.v1.jsonl"), limit=1)[0]
    request = task_to_request(task)
    assert request.topic == task["topic"]
    assert request.source_policy.value == "NO_SOURCES"


@pytest.mark.asyncio
async def test_dry_run_never_calls_registry(tmp_path) -> None:
    class ExplodingRegistry:
        def cloud_llm(self): raise AssertionError("cloud must not be called")
    records = await run_eval(load_tasks(Path("data/eval/curriculum/tasks.v1.jsonl"), limit=1), mode="architecture", output_dir=tmp_path, dry_run=True, registry=ExplodingRegistry())
    assert records[0]["dry_run"] is True
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_collects_sanitized_fallback_and_repair_events(tmp_path) -> None:
    class FakeCloud:
        def __init__(self):
            self.events = [
                {"model": "primary", "kind": "structured", "status": "invalid", "latency_ms": 3, "fallback": False, "repair": True, "prompt_tokens": 4, "output_tokens": 2, "total_tokens": 6, "error_type": "ValidationError"},
                {"model": "fallback", "kind": "structured", "status": "success", "latency_ms": 5, "fallback": True, "repair": False, "prompt_tokens": 4, "output_tokens": 3, "total_tokens": 7},
            ]
        def drain_attempt_log(self):
            events, self.events = self.events, []
            return events
        async def generate_structured(self, prompt, **kwargs):
            return StructuredGeneration(value=CurriculumDraft(topic_title="x", target_level="x", pedagogical_approach="x", learning_objectives=["x"], syllabus_units=[CurriculumUnitDraft(unit_number=1, unit_name="x", estimated_hours=1, subtopics=["x"], didactic_explanation="x")]), model="fallback", usage=TokenUsage(total_tokens=7))
    class Registry:
        def __init__(self): self.cloud = FakeCloud()
        def cloud_llm(self): return self.cloud
    task = load_tasks(Path("data/eval/curriculum/tasks.v1.jsonl"), limit=1)
    records = await run_eval(task, mode="architecture", output_dir=tmp_path, registry=Registry())
    assert records[0]["attempts"] == 2
    assert records[0]["fallbacks"] == 1 and records[0]["repairs"] == 1
    assert records[0]["operations"]["architecture"]["events"][0]["error_type"] == "ValidationError"
    saved = json.loads((tmp_path / "cur-001.json").read_text(encoding="utf-8"))
    assert saved["curriculum"]["grounding_status"] == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_observable_variant_is_selected_and_hashed(tmp_path) -> None:
    class Cloud:
        async def generate_structured(self, prompt, *, system_instruction, **kwargs):
            assert system_instruction == CURRICULUM_ARCHITECT_OBSERVABLE_V2_PROMPT
            return StructuredGeneration(value=CurriculumDraft(topic_title="x", target_level="x", pedagogical_approach="x", learning_objectives=["Resolver x"], syllabus_units=[CurriculumUnitDraft(unit_number=1, unit_name="x", estimated_hours=1, subtopics=["x"], didactic_explanation="x")]), model="fake", usage=TokenUsage(total_tokens=1))
    class Registry:
        def cloud_llm(self): return Cloud()
    task = load_tasks(Path("data/eval/curriculum/tasks.v1.jsonl"), limit=1)
    records = await run_eval(task, mode="architecture", output_dir=tmp_path, registry=Registry(), prompt_variant="observable-v2")
    assert records[0]["prompt_variant"] == "observable-v2"
    assert records[0]["status"] == "completed"
