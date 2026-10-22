import json

import pytest

from evals.dataset import judgments_for, load_dataset


DATASET = "data/eval/retrieval/dataset.v1.jsonl"


def test_loads_non_test_splits_and_derives_qrels() -> None:
    cases = load_dataset(DATASET)
    assert len(cases) == 36
    assert {case.split for case in cases} == {"calibration", "dev"}
    case = next(item for item in cases if item.query_id == "live-cal-002")
    assert case.relevant_ids == ["web-sep-algebra-smoke:e521976fb2a49137"]
    assert judgments_for(case)[0].relevance == 2
    assert case.allowed_source_ids == ["web-sep-algebra-smoke"]
    assert case.answerable is True


def test_test_split_is_opt_in() -> None:
    assert len(load_dataset(DATASET, include_test=True)) == 48
    assert all(case.split != "test" for case in load_dataset(DATASET))


def test_rejects_duplicate_ids_and_invalid_values(tmp_path) -> None:
    row = {"query_id": "same", "split": "dev", "query": "x", "qrels": {"a": 2}}
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row) + "\n" + json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate query_id"):
        load_dataset(path)

    path.write_text(json.dumps({**row, "split": "oops"}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid dataset row"):
        load_dataset(path)

    path.write_text(json.dumps({**row, "qrels": {"a": 3}}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid dataset row"):
        load_dataset(path)


def test_legacy_relevant_ids_are_migrated_without_duplicate_storage() -> None:
    from evals.schemas import QueryCase

    case = QueryCase(query_id="legacy", query="q", relevant_ids=["a", "a"])
    assert case.qrels == {"a": 1}
    assert "relevant_ids" not in case.model_dump()
