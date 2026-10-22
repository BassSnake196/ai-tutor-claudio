"""Public contracts and pure metrics for offline retrieval evaluations."""

from .metrics import (
    abstention_metrics,
    aggregate_run,
    evaluate_query,
    hit_at_k,
    mrr_at_k,
    mean_reciprocal_rank_at_k,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    source_leakage_rate,
)
from .dataset import judgments_for, load_dataset
from .schemas import QueryCase, QueryMetrics, RankedResult, RelevanceJudgment, RunMetrics

__all__ = [
    "QueryCase",
    "QueryMetrics",
    "RankedResult",
    "RelevanceJudgment",
    "RunMetrics",
    "abstention_metrics",
    "aggregate_run",
    "evaluate_query",
    "hit_at_k",
    "mrr_at_k",
    "mean_reciprocal_rank_at_k",
    "ndcg_at_k",
    "percentile",
    "precision_at_k",
    "recall_at_k",
    "source_leakage_rate",
    "load_dataset",
    "judgments_for",
]
