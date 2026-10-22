from evals.hybrid import BM25Index, CorpusDocument, rrf_fuse, tokenize
from evals.runner import RankedCandidate

def test_spanish_tokenization_is_case_and_accent_insensitive():
    assert tokenize("ÁLGEBRA y evaluación") == ["algebra", "evaluacion"]

def test_bm25_is_deterministic_and_relevant_first():
    index = BM25Index([CorpusDocument("a", "fracciones y algebra", {}), CorpusDocument("b", "historia", {})])
    assert [x.candidate_id for x in index.search("álgebra")] == ["a"]
    assert index.search("álgebra")[0].metadata["sparse_score"] > 0

def test_rrf_deduplicates_and_preserves_component_scores():
    result = rrf_fuse([RankedCandidate("a", .9), RankedCandidate("b", .5)], [RankedCandidate("b", 2.0), RankedCandidate("a", 1.0)], limit=2)
    assert [x.candidate_id for x in result] == ["a", "b"]
    assert result[0].metadata["dense_score"] == .9
    assert result[0].metadata["sparse_score"] == 1.0
    assert result[0].metadata["fused_score"] == result[0].score
