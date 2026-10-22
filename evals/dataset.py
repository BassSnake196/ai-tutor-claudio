"""Strict JSONL loader for retrieval evaluation datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from .schemas import QueryCase, RelevanceJudgment


def load_dataset(path: str | Path, *, include_test: bool = False) -> list[QueryCase]:
    """Load JSONL cases, excluding the held-out ``test`` split by default."""
    cases: list[QueryCase] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                case = QueryCase.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid dataset row at line {line_number}: {exc}") from exc
            if case.query_id in seen:
                raise ValueError(f"duplicate query_id: {case.query_id}")
            seen.add(case.query_id)
            if case.split != "test" or include_test:
                cases.append(case)
    return cases


def judgments_for(case: QueryCase) -> list[RelevanceJudgment]:
    """Return qrels as typed judgments without creating a second source of truth."""
    return [RelevanceJudgment(result_id=result_id, relevance=relevance) for result_id, relevance in case.qrels.items()]
