"""Offline threshold/k calibration from one raw top-20 retrieval run."""
from __future__ import annotations
import csv, json
from pathlib import Path
from typing import Any, Sequence
from .metrics import aggregate_run, evaluate_query
from .schemas import QueryCase, RankedResult

KS = (3, 5, 10, 20)
THRESHOLDS = tuple(round(x / 100, 2) for x in range(20, 91, 5))

def load_raw(path: str | Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8")); manifest = payload.get("manifest", {})
    if int(manifest.get("k", 0)) < 20: raise ValueError("raw run must contain top-20 candidates")
    queries = {str(row["case_id"]): row.get("candidates", []) for row in payload.get("queries", [])}
    return manifest, queries

def calibrate(manifest: dict[str, Any], queries: dict[str, list[dict[str, Any]]], cases: Sequence[QueryCase], *, thresholds=THRESHOLDS, ks=KS) -> list[dict[str, Any]]:
    by_id = {case.query_id: case for case in cases}; rows = []
    for threshold in thresholds:
        for k in ks:
            query_metrics = []
            for query_id, case in by_id.items():
                candidates = [item for item in queries.get(query_id, []) if float(item.get("score", 0)) >= threshold][:k]
                ranked = [RankedResult(result_id=str(item["candidate_id"]), source_id=(item.get("metadata") or {}).get("source_id")) for item in candidates]
                query_metrics.append(evaluate_query(case, ranked, k=k, abstained=not ranked))
            aggregate = aggregate_run(query_metrics, k=k).model_dump()
            abstention = sum(item.abstained for item in query_metrics) / max(len(query_metrics), 1)
            rows.append({"model": manifest.get("model", "unknown"), "collection": manifest.get("collection"), "threshold": threshold, "k": k, "retrieval": aggregate, "abstention_rate": abstention})
    return rows

def _selection(row: dict[str, Any]) -> dict[str, Any]:
    return {"model": row["model"], "collection": row["collection"], "k": row["k"], "threshold": row["threshold"], "retrieval": row["retrieval"], "abstention_rate": row["abstention_rate"]}

def recommend(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows: raise ValueError("no calibration rows")
    # Caller supplies one model at a time; score scales are never compared across models.
    quality = max(rows, key=lambda r: (r["retrieval"].get("ndcg_at_k") or -1, r["retrieval"].get("recall_at_k") or -1, r["retrieval"].get("mrr_at_k") or -1, -r["k"], -r["threshold"]))
    known = [r for r in rows if r["retrieval"].get("abstention_accuracy") is not None]
    if not known:
        return {"model": quality["model"], "collection": quality["collection"], "quality": _selection(quality), "context": None, "balanced": None, "abstention": None}
    balanced = max(known, key=lambda r: (min(r["retrieval"].get("recall_at_k") or 0, r["retrieval"].get("abstention_accuracy") or 0), r["retrieval"].get("ndcg_at_k") or -1, r["retrieval"].get("mrr_at_k") or -1, -r["k"], -r["threshold"]))
    max_recall = max((r["retrieval"].get("recall_at_k") or 0) for r in rows)
    eligible = [r for r in known if (r["retrieval"].get("recall_at_k") or 0) >= .95 * max_recall]
    abstention = max(eligible, key=lambda r: (r["retrieval"].get("abstention_accuracy") or -1, r["retrieval"].get("ndcg_at_k") or -1, -r["k"], -r["threshold"])) if eligible else None
    context_rows = [r for r in known if r["k"] <= 10]
    context = max(context_rows, key=lambda r: (min(r["retrieval"].get("recall_at_k") or 0, r["retrieval"].get("abstention_accuracy") or 0), r["retrieval"].get("ndcg_at_k") or -1, r["retrieval"].get("mrr_at_k") or -1, -r["k"], -r["threshold"])) if context_rows else None
    return {"model": quality["model"], "collection": quality["collection"], "quality": _selection(quality), "context": None if context is None else _selection(context), "balanced": _selection(balanced), "abstention": None if abstention is None else _selection(abstention)}

def write_calibration(directory: str | Path, rows: Sequence[dict[str, Any]], recommendation: dict[str, Any]) -> dict[str, Path]:
    out = Path(directory); out.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, md_path = out / "calibration.json", out / "calibration.csv", out / "calibration.md"
    json_path.write_text(json.dumps({"recommendation": recommendation, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["profile", "model", "collection", "threshold", "k", "recall_at_k", "precision_at_k", "mrr_at_k", "hit_at_k", "abstention_rate", "latency_p95_ms"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        choices = {tuple((choice or {}).get(key) for key in ("k", "threshold")): profile for profile, choice in recommendation.items() if profile in {"quality", "context", "balanced", "abstention"} and choice}
        for row in rows:
            metrics = row["retrieval"]; profile = choices.get((row["k"], row["threshold"]), "")
            writer.writerow({"profile": profile, "model": row["model"], "collection": row["collection"], "threshold": row["threshold"], "k": row["k"], **{key: metrics.get(key) for key in fields[5:] if key != "abstention_rate"}, "abstention_rate": row["abstention_rate"]})
    lines = ["# Retrieval calibration", "", f"Model: `{recommendation['model']}`", ""]
    for profile in ("quality", "context", "balanced", "abstention"):
        choice = recommendation.get(profile)
        lines.append(f"- **{profile}**: unavailable" if choice is None else f"- **{profile}**: `k={choice['k']}`, threshold `{choice['threshold']}`")
    lines += ["", "`quality` is a potential pool profile; `context` is limited to k<=10 because runtime context is capped at 12. k=20 is never a final context recommendation.", "Retrieval and abstention are reported separately; profiles are selected per model without cross-model score comparisons.", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}
