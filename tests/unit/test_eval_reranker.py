import pytest

from evals.reranker import FakeRerankerScorer, LazyCrossEncoderReranker, RerankedBackend, TransformersCrossEncoderScorer


def test_fake_reranker_is_deterministic_and_preserves_separate_scores() -> None:
    reranker = LazyCrossEncoderReranker(scorer=FakeRerankerScorer())
    ranked = reranker.rank("alpha", [{"id": "b", "score": .9, "metadata": {"content": "beta"}}, {"id": "a", "score": .1, "metadata": {"content": "alpha"}}], top_k=1)
    assert ranked[0].candidate_id == "a"
    assert ranked[0].retrieval_score == .1
    assert ranked[0].rerank_score == 1


def test_exported_result_id_and_flat_metadata_are_normalized() -> None:
    reranker = LazyCrossEncoderReranker(scorer=FakeRerankerScorer())
    ranked = reranker.rank(
        "alpha",
        [{"result_id": "b", "score": .9, "source_id": "src", "content": "beta"},
         {"result_id": "a", "score": .1, "source_id": "src", "content": "alpha"}],
        top_k=2,
    )
    assert [item.candidate_id for item in ranked] == ["a", "b"]
    assert ranked[0].metadata["source_id"] == "src"
    assert ranked[0].metadata["content"] == "alpha"


def test_lazy_model_does_not_import_or_load_on_construction() -> None:
    reranker = LazyCrossEncoderReranker()
    assert reranker._model is None
    assert reranker.load_error is None


def test_transformers_engine_is_explicit_and_restricted() -> None:
    scorer = TransformersCrossEncoderScorer()
    assert scorer.model_name == "BAAI/bge-reranker-v2-m3"
    with pytest.raises(ValueError): TransformersCrossEncoderScorer("other-model")


@pytest.mark.asyncio
async def test_backend_fetches_top_n_and_returns_top_k() -> None:
    class Backend:
        def __init__(self): self.args = None
        def search(self, query, *, limit, score_threshold):
            self.args = (query, limit, score_threshold)
            return [{"id": "x", "score": 1, "metadata": {"content": "query"}}]
    backend = Backend()
    wrapped = RerankedBackend(backend, LazyCrossEncoderReranker(scorer=FakeRerankerScorer()), candidate_limit=20, top_k=5)
    await wrapped.search("query", limit=5, score_threshold=.3)
    assert backend.args == ("query", 20, .3)


def test_invalid_limits_and_score_count_are_rejected() -> None:
    with pytest.raises(ValueError): LazyCrossEncoderReranker(scorer=FakeRerankerScorer()).rank("x", [], top_k=0)
    with pytest.raises(ValueError): RerankedBackend(object(), LazyCrossEncoderReranker(scorer=FakeRerankerScorer()), candidate_limit=2, top_k=3)
