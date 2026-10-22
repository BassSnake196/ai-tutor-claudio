"""Serialization for isolated retrieval evaluation runs."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any, Sequence
from .runner import QueryResult

def _rows(results: Sequence[QueryResult]) -> list[dict[str, Any]]:
    return [{"case_id": r.case_id, "query": r.query, "latency_ms": round(r.latency_ms, 3),
             "error": r.error, "rank": i, "candidate_id": c.candidate_id, "score": c.score,
             "candidate_metadata": dict(c.metadata)} for r in results for i, c in enumerate(r.candidates, 1)]

def write_report(directory: str | Path, manifest: dict[str, Any], results: Sequence[QueryResult]) -> dict[str, Path]:
    out = Path(directory); out.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, md_path = out / "run.json", out / "ranked_candidates.csv", out / "report.md"
    payload = {"manifest": manifest, "queries": [{"case_id": r.case_id, "query": r.query,
        "latency_ms": r.latency_ms, "error": r.error, "candidates": [{"candidate_id": c.candidate_id,
        "score": c.score, "metadata": dict(c.metadata)} for c in r.candidates]} for r in results]}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = _rows(results)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "query", "latency_ms", "error", "rank", "candidate_id", "score", "candidate_metadata"])
        writer.writeheader(); writer.writerows(rows)
    latencies = [r.latency_ms for r in results]
    metrics = manifest.get("metrics", {})
    metric_lines = "".join(f"- {key}: {value}\n" for key, value in metrics.items())
    md_path.write_text("# Retrieval evaluation\n\n" + f"- Run: `{manifest['run_id']}`\n- Model: `{manifest['model']}`\n- Collection: `{manifest['collection']}`\n- Queries: {len(results)}\n- Latency mean (ms): {sum(latencies) / len(latencies) if latencies else 0:.3f}\n- Errors: {sum(r.error is not None for r in results)}\n\n## Aggregate metrics\n\n" + (metric_lines or "Metrics unavailable.\n"), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}
