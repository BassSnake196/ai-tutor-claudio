"""Pure, deterministic retrieval metrics with explicit empty-set semantics."""

from collections.abc import Collection, Sequence
from math import log2

from .schemas import QueryCase, QueryMetrics, RankedResult, RunMetrics


def _check_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")


def _unique_prefix(results: Sequence[RankedResult], k: int) -> list[RankedResult]:
    _check_k(k)
    seen: set[str] = set()
    unique: list[RankedResult] = []
    for result in results:
        if result.result_id in seen:
            continue
        seen.add(result.result_id)
        unique.append(result)
        if len(unique) == k:
            break
    return unique


def hit_at_k(results: Sequence[RankedResult], relevant_ids: Collection[str], k: int) -> float:
    """Return 1 when any unique top-k result is relevant, otherwise 0."""
    relevant = set(relevant_ids)
    return float(any(item.result_id in relevant for item in _unique_prefix(results, k)))


def precision_at_k(results: Sequence[RankedResult], relevant_ids: Collection[str], k: int) -> float:
    """Binary precision at k; duplicate result IDs are counted once, denominator is k."""
    relevant = set(relevant_ids)
    return sum(item.result_id in relevant for item in _unique_prefix(results, k)) / k


def recall_at_k(results: Sequence[RankedResult], relevant_ids: Collection[str], k: int) -> float | None:
    """Recall at k, or None when the query has no known relevant results."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    found = {item.result_id for item in _unique_prefix(results, k)} & relevant
    return len(found) / len(relevant)


def mean_reciprocal_rank_at_k(
    results: Sequence[RankedResult], relevant_ids: Collection[str], k: int
) -> float:
    relevant = set(relevant_ids)
    for rank, item in enumerate(_unique_prefix(results, k), start=1):
        if item.result_id in relevant:
            return 1 / rank
    return 0.0


# Short public alias matching the conventional metric name.
mrr_at_k = mean_reciprocal_rank_at_k


def ndcg_at_k(
    results: Sequence[RankedResult],
    relevance_by_id: dict[str, int],
    k: int,
) -> float | None:
    """nDCG@k for graded relevance 0/1/2; None means no judged relevant item."""
    _check_k(k)
    if any(value not in (0, 1, 2) for value in relevance_by_id.values()):
        raise ValueError("relevance must be 0, 1, or 2")
    ideal = sorted(relevance_by_id.values(), reverse=True)[:k]
    if not ideal or ideal[0] == 0:
        return None
    top = _unique_prefix(results, k)
    dcg = sum((relevance_by_id.get(item.result_id, 0)) / log2(rank + 2) for rank, item in enumerate(top))
    idcg = sum(value / log2(rank + 2) for rank, value in enumerate(ideal))
    return dcg / idcg if idcg else None


def source_leakage_rate(results: Sequence[RankedResult], allowed_source_ids: Collection[str], k: int) -> float:
    """Fraction of unique top-k results whose source is outside the allow-list.

    With an empty allow-list, leakage is defined as 0 (no source restriction was declared).
    Results without a source are not leakage, but should be tracked separately by callers.
    """
    allowed = set(allowed_source_ids)
    top = _unique_prefix(results, k)
    if not top or not allowed:
        return 0.0
    return sum(item.source_id is not None and item.source_id not in allowed for item in top) / len(top)


def abstention_metrics(cases: Sequence[QueryCase], abstained: Sequence[bool]) -> tuple[float, float | None]:
    if len(cases) != len(abstained):
        raise ValueError("cases and abstained must have equal length")
    if not cases:
        return 0.0, None
    known = [(case, flag) for case, flag in zip(cases, abstained, strict=True) if case.answerable is not None]
    accuracy = None if not known else sum(flag is (not case.answerable) for case, flag in known) / len(known)
    return sum(abstained) / len(abstained), accuracy


def percentile(values: Sequence[float], p: float) -> float | None:
    if not 0 <= p <= 100:
        raise ValueError("p must be between 0 and 100")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * p / 100
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def evaluate_query(case: QueryCase, results: Sequence[RankedResult], *, k: int, abstained: bool = False, latency_ms: float | None = None) -> QueryMetrics:
    judgments = {item.result_id: item.relevance for item in case.relevance_judgments}
    graded = ndcg_at_k(results, judgments, k) if judgments else None
    abstention_correct = None if case.answerable is None else abstained is (not case.answerable)
    return QueryMetrics(
        query_id=case.query_id, k=k,
        hit=hit_at_k(results, case.relevant_ids, k),
        precision=precision_at_k(results, case.relevant_ids, k),
        recall=recall_at_k(results, case.relevant_ids, k),
        mrr=mean_reciprocal_rank_at_k(results, case.relevant_ids, k),
        ndcg=graded,
        source_leakage=source_leakage_rate(results, case.allowed_source_ids, k),
        abstained=abstained, abstention_correct=abstention_correct, latency_ms=latency_ms,
    )


def aggregate_run(metrics: Sequence[QueryMetrics], *, k: int | None = None) -> RunMetrics:
    if not metrics:
        return RunMetrics(query_count=0, evaluated_retrieval_queries=0, evaluated_recall_queries=0, source_leakage_rate=0, abstention_rate=0)
    chosen_k = k or metrics[0].k
    if any(item.k != chosen_k for item in metrics):
        raise ValueError("all query metrics must use the same k")
    retrieval = [item for item in metrics if item.recall is not None]
    recalls = [item.recall for item in retrieval if item.recall is not None]
    ndcgs = [item.ndcg for item in metrics if item.ndcg is not None]
    known_abstentions = [item.abstention_correct for item in metrics if item.abstention_correct is not None]
    latencies = [item.latency_ms for item in metrics if item.latency_ms is not None]
    return RunMetrics(
        query_count=len(metrics), evaluated_retrieval_queries=len(retrieval), evaluated_recall_queries=len(recalls),
        hit_at_k=None if not retrieval else sum(item.hit for item in retrieval) / len(retrieval),
        precision_at_k=None if not retrieval else sum(item.precision for item in retrieval) / len(retrieval),
        recall_at_k=None if not recalls else sum(recalls) / len(recalls),
        mrr_at_k=None if not retrieval else sum(item.mrr for item in retrieval) / len(retrieval),
        ndcg_at_k=None if not ndcgs else sum(ndcgs) / len(ndcgs),
        source_leakage_rate=0 if not retrieval else sum(item.source_leakage for item in retrieval) / len(retrieval),
        abstention_rate=sum(item.abstained for item in metrics) / len(metrics),
        abstention_accuracy=None if not known_abstentions else sum(known_abstentions) / len(known_abstentions),
        latency_p50_ms=percentile(latencies, 50), latency_p95_ms=percentile(latencies, 95),
    )
