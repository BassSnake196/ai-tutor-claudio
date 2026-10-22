from math import log2

import pytest

from evals.metrics import (
    abstention_metrics,
    aggregate_run,
    evaluate_query,
    hit_at_k,
    mean_reciprocal_rank_at_k,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    source_leakage_rate,
)
from evals.schemas import QueryCase, QueryMetrics, RankedResult, RelevanceJudgment


def results(*ids: str) -> list[RankedResult]:
    return [RankedResult(result_id=item) for item in ids]


def test_binary_metrics_manual_values_and_duplicates() -> None:
    ranked = results("a", "a", "b", "c")
    # Duplicate IDs are collapsed before taking the k unique results.
    assert hit_at_k(ranked, {"b"}, 2) == 1
    assert precision_at_k(ranked, {"b"}, 3) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, {"a", "b"}, 3) == 1
    assert mean_reciprocal_rank_at_k(ranked, {"b"}, 3) == pytest.approx(1 / 2)


def test_ndcg_graded_manual_value() -> None:
    ranked = results("a", "b", "c")
    # Ranked gains are 2, 0, 1; ideal gains are 2, 1, 0.
    expected = (2 + 1 / log2(4)) / (2 + 1 / log2(3))
    assert ndcg_at_k(ranked, {"a": 2, "b": 0, "c": 1}, 3) == pytest.approx(expected)
    assert ndcg_at_k(results("x"), {"a": 0}, 3) is None


def test_empty_relevant_set_is_explicitly_excluded_from_recall() -> None:
    ranked = results("a")
    assert recall_at_k(ranked, set(), 5) is None
    assert ndcg_at_k(ranked, {"a": 0}, 5) is None
    assert precision_at_k(ranked, set(), 5) == 0


def test_source_leakage_and_abstention() -> None:
    ranked = [RankedResult(result_id="a", source_id="ok"), RankedResult(result_id="b", source_id="leak")]
    assert source_leakage_rate(ranked, {"ok"}, 2) == pytest.approx(0.5)
    cases = [QueryCase(query_id="1", query="x", answerable=True), QueryCase(query_id="2", query="y", answerable=False)]
    assert abstention_metrics(cases, [True, True]) == (1.0, 0.5)


def test_aggregate_uses_only_defined_recall_and_linear_percentiles() -> None:
    items = [
        QueryMetrics(query_id="1", k=2, hit=1, precision=0.5, recall=1, mrr=1, ndcg=1, source_leakage=0, abstained=False, latency_ms=10),
        QueryMetrics(query_id="2", k=2, hit=0, precision=0, recall=None, mrr=0, ndcg=None, source_leakage=1, abstained=True, latency_ms=20),
        QueryMetrics(query_id="3", k=2, hit=1, precision=0.5, recall=0.5, mrr=0.5, ndcg=0.5, source_leakage=0, abstained=False, latency_ms=30),
    ]
    run = aggregate_run(items)
    assert run.evaluated_retrieval_queries == 2
    assert run.hit_at_k == pytest.approx(1)
    assert run.evaluated_recall_queries == 2
    assert run.recall_at_k == pytest.approx(0.75)
    assert run.latency_p50_ms == 20
    assert run.latency_p95_ms == pytest.approx(29)


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        hit_at_k([], set(), 0)
    with pytest.raises(ValueError):
        ndcg_at_k([], {"x": 3}, 1)
    with pytest.raises(ValueError):
        percentile([1], 101)
    with pytest.raises(ValueError):
        QueryCase(query_id="x", query="q", relevant_ids=["a", "a", ""])
    with pytest.raises(ValueError):
        RelevanceJudgment(result_id="x", relevance=3)


def test_mismatched_abstention_inputs_and_mixed_k_rejected() -> None:
    case = QueryCase(query_id="x", query="q")
    with pytest.raises(ValueError):
        abstention_metrics([case], [])
    with pytest.raises(ValueError):
        aggregate_run([QueryMetrics(query_id="1", k=1, hit=0, precision=0, mrr=0, source_leakage=0, abstained=False), QueryMetrics(query_id="2", k=2, hit=0, precision=0, mrr=0, source_leakage=0, abstained=False)])
