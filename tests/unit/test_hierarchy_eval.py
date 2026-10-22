import asyncio

from evals.hierarchy_eval import (
    HierarchyCase,
    ScriptedBackend,
    ScriptedExternal,
    FakeChunk,
    evaluate_case,
)


def complete(stage: str, source: str) -> dict[tuple[str, str], list[FakeChunk]]:
    return {(stage, category): [FakeChunk(f"{source}:{category}", 0.9, source, content=f"{source} evidencia {category}")] for category in ("concepts", "progression", "didactics", "assessment")}


def test_selected_sufficient_stops_without_expansion() -> None:
    case = HierarchyCase("selected", source_ids=("selected",), backend=ScriptedBackend(complete("SELECTED", "selected")))
    result = asyncio.run(evaluate_case(case))
    assert result.stages == ("SELECTED",)
    assert result.expansion_unnecessary is False
    assert result.external_executed is False


def test_uploaded_only_does_not_expand() -> None:
    backend = ScriptedBackend({("SELECTED", "concepts"): [FakeChunk("selected:concepts", 0.9, "selected")]})
    result = asyncio.run(evaluate_case(HierarchyCase("uploaded", "UPLOADED_ONLY", ("selected",), backend=backend)))
    assert result.stages == ("SELECTED",)
    assert result.external_executed is False


def test_external_allowed_records_required_and_execution() -> None:
    ext = ScriptedExternal({category: [FakeChunk(f"e:{category}", 0.9, "external")] for category in ("concepts", "progression", "didactics", "assessment")})
    result = asyncio.run(evaluate_case(HierarchyCase("external", "EXTERNAL_ALLOWED", backend=ScriptedBackend(), external=ext)))
    assert result.external_required is False
    assert result.external_executed is True
    assert result.stages[-1] == "EXTERNAL"

    unavailable = asyncio.run(
        evaluate_case(HierarchyCase("external-required", "EXTERNAL_ALLOWED", backend=ScriptedBackend()))
    )
    assert unavailable.external_required is True
    assert unavailable.external_executed is False


def test_archived_payload_is_flagged_and_duplicate_chunk_is_measurable() -> None:
    archived = ScriptedBackend({("LOCAL_LIBRARY", "concepts"): [FakeChunk("a", 0.9, "archived", status="DELETED")]})
    result = asyncio.run(evaluate_case(HierarchyCase("archived", backend=archived)))
    assert result.inactive_accepted is True

    duplicate = ScriptedBackend({("LOCAL_LIBRARY", category): [FakeChunk("same", 0.9, "local", content="same evidence")] for category in ("concepts", "progression", "didactics", "assessment")})
    deduped = asyncio.run(evaluate_case(HierarchyCase("duplicate", backend=duplicate)))
    assert deduped.duplicate_count >= 1


def test_adversarial_source_leakage_and_false_coverage_are_reported() -> None:
    leaked = ScriptedBackend(
        {
            ("SELECTED", category): [FakeChunk(f"other:{category}", 0.9, "other", content=f"other {category}")]
            for category in ("concepts", "progression", "didactics", "assessment")
        }
    )
    leak_result = asyncio.run(
        evaluate_case(HierarchyCase("leak", source_ids=("selected",), backend=leaked))
    )
    assert leak_result.source_leakage is True

    unrelated = ScriptedBackend(
        {
            ("LOCAL_LIBRARY", category): [FakeChunk(f"unrelated:{category}", 0.9, "local", content=f"unrelated {category}")]
            for category in ("concepts", "progression", "didactics", "assessment")
        }
    )
    coverage_result = asyncio.run(
        evaluate_case(
            HierarchyCase(
                "false-coverage",
                expected_relevant_ids=frozenset({"gold:not-present"}),
                backend=unrelated,
            )
        )
    )
    assert coverage_result.false_coverage is True
