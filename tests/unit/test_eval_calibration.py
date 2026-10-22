from evals.calibration import calibrate, recommend
from evals.schemas import QueryCase

def test_calibration_reuses_scores_and_separates_abstention():
    case = QueryCase(query_id="q1", query="x", qrels={"a": 2})
    rows = calibrate({"model": "m", "collection": "eval_m", "k": 20}, {"q1": [{"candidate_id": "a", "score": .9}, {"candidate_id": "b", "score": .1}]}, [case], thresholds=(.2, .9), ks=(3,))
    low, high = rows
    assert low["retrieval"]["recall_at_k"] == 1.0 and low["abstention_rate"] == 0
    assert high["abstention_rate"] == 0

def test_recommendation_does_not_compare_model_scales():
    rows = [{"model": "nomic", "collection": "a", "k": 5, "threshold": .2, "retrieval": {"recall_at_k": .8, "mrr_at_k": .4, "precision_at_k": .2}, "abstention_rate": 0}, {"model": "nomic", "collection": "a", "k": 10, "threshold": .3, "retrieval": {"recall_at_k": .8, "mrr_at_k": .4, "precision_at_k": .2}, "abstention_rate": 0}]
    result = recommend(rows)
    assert result["quality"]["k"] == 5
    assert result["balanced"] is None and result["context"] is None and result["abstention"] is None

def test_profiles_use_answerability_and_recall_constraint():
    base = {"model": "m", "collection": "eval", "abstention_rate": 0}
    rows = [
        {**base, "k": 3, "threshold": .2, "retrieval": {"ndcg_at_k": .5, "recall_at_k": .9, "mrr_at_k": .4, "abstention_accuracy": .5}},
        {**base, "k": 5, "threshold": .4, "retrieval": {"ndcg_at_k": .7, "recall_at_k": 1.0, "mrr_at_k": .6, "abstention_accuracy": .8}},
        {**base, "k": 10, "threshold": .6, "retrieval": {"ndcg_at_k": .6, "recall_at_k": .95, "mrr_at_k": .5, "abstention_accuracy": .9}},
    ]
    result = recommend(rows)
    assert result["quality"]["k"] == 5
    assert result["balanced"]["k"] == 10
    assert result["context"]["k"] == 10
    assert result["abstention"]["k"] == 10
