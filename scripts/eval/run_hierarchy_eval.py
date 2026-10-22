"""Run deterministic hierarchy/policy evaluation cases."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.hierarchy_eval import (
    EXTERNAL_STAGE,
    LOCAL_LIBRARY_STAGE,
    SELECTED_STAGE,
    FakeChunk,
    HierarchyCase,
    ScriptedBackend,
    ScriptedExternal,
    evaluate_cases,
)


def _complete(stage: str, source: str) -> dict[tuple[str, str], list[FakeChunk]]:
    return {
        (stage, category): [FakeChunk(f"{source}:{category}", 0.9, source, content=f"{source} evidencia {category}")]
        for category in ("concepts", "progression", "didactics", "assessment")
    }


def build_cases() -> list[HierarchyCase]:
    selected = ScriptedBackend(_complete(SELECTED_STAGE.value, "selected"))
    local = ScriptedBackend(_complete(LOCAL_LIBRARY_STAGE.value, "local"))
    external = ScriptedExternal({category: [FakeChunk(f"external:{category}", 0.8, "external")] for category in ("concepts", "progression", "didactics", "assessment")})
    insufficient = ScriptedBackend({(SELECTED_STAGE.value, "concepts"): [FakeChunk("selected:concepts", 0.9, "selected")]})
    partial = ScriptedBackend({(LOCAL_LIBRARY_STAGE.value, "concepts"): [FakeChunk("local:concepts", 0.9, "local")]})
    archived = ScriptedBackend({(LOCAL_LIBRARY_STAGE.value, "concepts"): [FakeChunk("archived:concepts", 0.9, "archived", status="DELETED")]})
    duplicate = ScriptedBackend({(LOCAL_LIBRARY_STAGE.value, category): [FakeChunk("same", 0.9, "local", content="same evidence")] for category in ("concepts", "progression", "didactics", "assessment")})
    false_coverage = ScriptedBackend(_complete(LOCAL_LIBRARY_STAGE.value, "unrelated"))
    leaked_selected = ScriptedBackend(_complete(SELECTED_STAGE.value, "other"))
    return [
        HierarchyCase("selected-sufficient", "LOCAL_FIRST", ("selected",), backend=selected),
        HierarchyCase("selected-insufficient-local", "LOCAL_FIRST", ("selected",), backend=insufficient),
        HierarchyCase("uploaded-only-insufficient", "UPLOADED_ONLY", ("selected",), backend=insufficient),
        HierarchyCase("external-allowed", "EXTERNAL_ALLOWED", (), backend=ScriptedBackend(), external=external),
        HierarchyCase("external-partial-failure", "EXTERNAL_ALLOWED", (), backend=partial, external=ScriptedExternal({}, failures={"progression", "didactics", "assessment"})),
        HierarchyCase("external-required-unavailable", "EXTERNAL_ALLOWED", (), backend=ScriptedBackend(), external=None),
        HierarchyCase("archived-payload", "LOCAL_FIRST", (), backend=archived),
        HierarchyCase("same-chunk-dedup", "LOCAL_FIRST", (), backend=duplicate),
        HierarchyCase("false-coverage", "LOCAL_FIRST", (), expected_relevant_ids=frozenset({"gold:not-present"}), backend=false_coverage),
        HierarchyCase("selected-source-leak", "LOCAL_FIRST", ("selected",), backend=leaked_selected),
    ]


def main() -> int:
    results = asyncio.run(evaluate_cases(build_cases()))
    summary = {
        "case_count": len(results),
        "policy_clean_cases": sum(
            not item.source_leakage
            and not item.expansion_unnecessary
            and not item.false_coverage
            and not item.inactive_accepted
            for item in results
        ),
        "inactive_accepted_cases": sum(item.inactive_accepted for item in results),
        "false_coverage_cases": sum(item.false_coverage for item in results),
        "results": [item.as_dict() for item in results],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
