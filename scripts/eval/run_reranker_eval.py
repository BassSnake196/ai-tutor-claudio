"""Offline reranker comparison; accepts pre-recorded retrieval candidates."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.dataset import load_dataset
from evals.metrics import aggregate_run, evaluate_query
from evals.reranker import FakeRerankerScorer, LazyCrossEncoderReranker, TransformersCrossEncoderScorer
from evals.schemas import RankedResult


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/eval/retrieval/dataset.v1.jsonl")
    parser.add_argument("--candidates", required=True, help="JSONL: query_id, candidates [{result_id,score,source_id,content}]")
    parser.add_argument("--model", default="fake", choices=("fake", "bge"))
    parser.add_argument("--engine", default="fake", choices=("fake", "transformers"))
    parser.add_argument("--input-model", default="unknown", help="model that produced the top-N candidates")
    parser.add_argument("--output", default="docs/evaluation/RERANKER_RESULTS.md")
    args = parser.parse_args()
    cases = {case.query_id: case for case in load_dataset(args.dataset)}
    if args.engine == "transformers":
        reranker = LazyCrossEncoderReranker(scorer=TransformersCrossEncoderScorer())
    else:
        reranker = LazyCrossEncoderReranker(scorer=FakeRerankerScorer())
    baseline, reranked, errors = [], [], []
    for row in map(json.loads, Path(args.candidates).read_text(encoding="utf-8").splitlines()):
        case = cases.get(row["query_id"])
        if case is None: continue
        candidates = row.get("candidates", [])[:20]
        base = [RankedResult(result_id=str(item["result_id"]), source_id=item.get("source_id")) for item in candidates[:5]]
        started = time.perf_counter()
        try:
            ranked = reranker.rank(case.query, candidates, top_k=5)
            latency = (time.perf_counter() - started) * 1000
            improved = [RankedResult(result_id=item.candidate_id, source_id=item.metadata.get("source_id")) for item in ranked]
            baseline.append(evaluate_query(case, base, k=5, latency_ms=0))
            reranked.append(evaluate_query(case, improved, k=5, latency_ms=latency))
        except Exception as exc:
            errors.append(f"{case.query_id}: {type(exc).__name__}: {exc}")
    report = "# Reranker experimental\n\n"
    report += f"Modelo: `{args.model}`; casos calibration/dev (test excluido): {len(reranked)}; errores: {len(errors)}.\n\n"
    if baseline and reranked:
        report += "| Configuración | Hit@5 | MRR@5 | nDCG@5 | p50 ms | p95 ms |\n|---|---:|---:|---:|---:|---:|\n"
        for name, values in ((f"Baseline {args.input_model} top-20→5", baseline), (f"Reranked {args.model} top-20→5", reranked)):
            run = aggregate_run(values)
            report += f"| {name} | {run.hit_at_k:.3f} | {run.mrr_at_k:.3f} | {run.ndcg_at_k or 0:.3f} | {run.latency_p50_ms or 0:.1f} | {run.latency_p95_ms or 0:.1f} |\n"
    report += "\nDecisión: `defer` hasta medir recall/latencia/RAM con el modelo real.\n"
    if errors: report += "\nErrores:\n\n" + "\n".join(f"- {error}" for error in errors) + "\n"
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(report, encoding="utf-8")


if __name__ == "__main__": main()
