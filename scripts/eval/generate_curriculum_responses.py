"""Bounded offline/optional cloud curriculum generation evaluator."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.critic_agent import CurriculumCritic
from app.agents.curriculum_agent import CurriculumAgent
from app.agents.prompts import CURRICULUM_ARCHITECT_OBSERVABLE_V2_PROMPT, CURRICULUM_ARCHITECT_SYSTEM_PROMPT, TEACHING_SYSTEM_PROMPT
from app.agents.teaching_agent import TeachingAgent
from app.ai.registry import ModelRegistry
from app.core.config import Settings
from app.schemas.requests import CurriculumRequest
from app.schemas.source_resolution import SourcePolicy
from evals.operation_eval import summarize


def load_tasks(path: Path, *, split: str | None = None, limit: int | None = None, include_test: bool = False, no_sources_only: bool = True) -> list[dict[str, Any]]:
    tasks = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip(): continue
        try: task = json.loads(line)
        except json.JSONDecodeError as exc: raise ValueError(f"invalid task line {line_no}") from exc
        if task.get("split") == "test" and not include_test: continue
        if split and task.get("split") != split: continue
        if no_sources_only and task.get("policy") != "NO_SOURCES": continue
        tasks.append(task)
        if limit is not None and len(tasks) >= limit: break
    return tasks


def task_to_request(task: dict[str, Any]) -> CurriculumRequest:
    return CurriculumRequest(topic=task["topic"], target_level=task["level"], duration_weeks=task["weeks"], hours_per_week=task["hours_per_week"], desired_outcomes=task.get("expectations", []), source_ids=task.get("source_ids", []), source_policy=SourcePolicy(task["policy"]))


def _hash(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()[:16]


def _collect_operations(provider: Any, record: dict[str, Any], stage: str) -> None:
    drain = getattr(provider, "drain_attempt_log", None)
    events = drain() if callable(drain) else []
    if not events:
        return
    # Provider events are already sanitized; whitelist fields defensively.
    safe = [{key: event[key] for key in ("model", "kind", "status", "latency_ms", "fallback", "repair", "prompt_tokens", "output_tokens", "total_tokens", "error_type") if key in event} for event in events]
    record.setdefault("operations", {})[stage] = {"events": safe, "summary": summarize(safe)}
    record["attempts"] = sum(item["summary"]["calls"] for item in record["operations"].values())
    record["fallbacks"] = sum(item["summary"]["fallbacks"] for item in record["operations"].values())
    record["repairs"] = sum(item["summary"]["repairs"] for item in record["operations"].values())


async def run_eval(tasks: Sequence[dict[str, Any]], *, mode: str, output_dir: Path, dry_run: bool = False, registry: Any | None = None, prompt_variant: str = "baseline") -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return [{"task_id": task["task_id"], "split": task["split"], "mode": mode, "dry_run": True} for task in tasks]
    registry = registry or ModelRegistry(Settings())
    results = []
    for task in tasks:
        task_id, started = task["task_id"], time.perf_counter()
        artifact = output_dir / f"{task_id}.json"
        architecture_prompt = CURRICULUM_ARCHITECT_OBSERVABLE_V2_PROMPT if prompt_variant == "observable-v2" else CURRICULUM_ARCHITECT_SYSTEM_PROMPT
        record: dict[str, Any] = {"task_id": task_id, "split": task["split"], "mode": mode, "prompt_variant": prompt_variant, "status": "error", "prompt_hashes": {"curriculum_architect": _hash(architecture_prompt), "teaching": _hash(TEACHING_SYSTEM_PROMPT)}, "attempts": 0, "fallbacks": 0, "repairs": 0, "errors": []}
        try:
            request = task_to_request(task)
            architecture_data = None
            if mode == "full" and artifact.exists():
                architecture_data = json.loads(artifact.read_text(encoding="utf-8")).get("architecture")
            cloud = registry.cloud_llm()
            if architecture_data is None:
                record["attempts"] += 1
                try:
                    architecture = await CurriculumAgent(cloud).design(request, None, system_prompt=architecture_prompt)
                finally:
                    _collect_operations(cloud, record, "architecture")
                architecture_data = architecture.value.model_dump()
                record["architecture_model"] = architecture.model
                record["architecture_usage"] = architecture.usage.__dict__
            else:
                record["architecture_reused"] = True
            from app.schemas.curriculum_schema import CurriculumDraft
            draft = CurriculumDraft.model_validate(architecture_data)
            final_draft = draft
            if mode == "full":
                record["attempts"] += 1
                try:
                    teaching = await TeachingAgent(cloud).enrich(request, draft, None)
                finally:
                    _collect_operations(cloud, record, "teaching")
                final_draft = teaching.value
                record["teaching_model"] = teaching.model
                record["teaching_usage"] = teaching.usage.__dict__
            audit = CurriculumCritic().finalize(request, final_draft, None)
            record.update({"status": "completed", "curriculum": audit.curriculum.model_dump(mode="json"), "warnings": audit.warnings})
            record["architecture"] = architecture_data
        except Exception as exc:
            record["errors"].append({"type": type(exc).__name__, "message": str(exc)[:500]})
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        artifact.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(record)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("data/eval/curriculum/tasks.v1.jsonl"))
    parser.add_argument("--split", choices=("calibration", "dev", "test"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-test", action="store_true")
    parser.add_argument("--all-policies", action="store_true")
    parser.add_argument("--mode", choices=("architecture", "full"), default="architecture")
    parser.add_argument("--prompt-variant", choices=("baseline", "observable-v2"), default="baseline")
    parser.add_argument("--output-dir", type=Path, default=Path("data/eval/runs/curriculum_latest"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    tasks = load_tasks(args.tasks, split=args.split, limit=args.limit, include_test=args.include_test, no_sources_only=not args.all_policies)
    records = asyncio.run(run_eval(tasks, mode=args.mode, output_dir=args.output_dir, dry_run=args.dry_run, prompt_variant=args.prompt_variant))
    print(json.dumps({"count": len(records), "task_ids": [record["task_id"] for record in records]}, ensure_ascii=False))


if __name__ == "__main__": main()
