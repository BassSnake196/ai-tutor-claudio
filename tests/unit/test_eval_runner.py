import asyncio
import json
from pathlib import Path
import pytest
from evals.reporting import write_report
from evals.runner import RankedCandidate, RetrievalCase, RetrievalRunner

class FakeBackend:
    def search(self, query, *, limit, score_threshold):
        return [RankedCandidate("a", .9), RankedCandidate("b", .4), RankedCandidate("c", .1)]

def test_runner_is_reproducible_and_truncates_candidates():
    runner = RetrievalRunner(FakeBackend(), collection="eval_nomic", model="nomic-embed-text", k=2, seed=7)
    manifest, results = asyncio.run(runner.run([RetrievalCase("q1", "¿qué es evaluación?", ("a",))], run_id="fixed"))
    assert manifest["run_id"] == "fixed"; assert manifest["collection"] == "eval_nomic"
    assert [c.candidate_id for c in results[0].candidates] == ["a", "b"]
    assert results[0].latency_ms >= 0
    assert manifest["metrics"]["recall_at_k"] == 1.0
    assert manifest["query_metrics"][0]["query_id"] == "q1"

def test_production_collection_is_rejected():
    with pytest.raises(ValueError, match="production collection"):
        RetrievalRunner(FakeBackend(), collection="tutor_documents")

def test_reporting_writes_json_csv_and_markdown(tmp_path: Path):
    runner = RetrievalRunner(FakeBackend(), collection="eval_fake")
    manifest, results = asyncio.run(runner.run([RetrievalCase("q1", "x")]))
    paths = write_report(tmp_path, manifest, results)
    assert {p.suffix for p in paths.values()} == {".json", ".csv", ".md"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["queries"][0]["candidates"][0]["candidate_id"] == "a"
