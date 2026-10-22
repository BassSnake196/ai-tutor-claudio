"""Evaluate recorded curriculum JSONL responses without cloud or auto-judge."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.curriculum_eval import validate_curriculum
from evals.prompt_registry import fingerprint

def main() -> int:
    p = argparse.ArgumentParser(description="Run deterministic recorded curriculum evaluation")
    p.add_argument("--tasks", type=Path, required=True); p.add_argument("--responses", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--split", choices=("calibration", "dev", "test"), default="calibration"); p.add_argument("--allow-test", action="store_true")
    p.add_argument("--prompt", default="curriculum-eval-v1"); p.add_argument("--model", default="recorded-fake")
    a = p.parse_args()
    if a.split == "test" and not a.allow_test: p.error("test split requires --allow-test")
    task_rows = [json.loads(line) for line in a.tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = [t for t in task_rows if t.get("split") == a.split]
    recorded = {str(x["task_id"]): x["response"] for x in (json.loads(line) for line in a.responses.read_text(encoding="utf-8").splitlines() if line.strip())}
    rows = [{"task_id": t["task_id"], **validate_curriculum(t, recorded[t["task_id"]])} for t in tasks if t["task_id"] in recorded]
    a.output.mkdir(parents=True, exist_ok=True); payload = {"provenance": fingerprint(prompt=a.prompt, model=a.model, config={"split": a.split}), "split": a.split, "results": rows}
    (a.output / "curriculum_eval.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (a.output / "curriculum_eval.md").write_text("# Curriculum evaluation\n\n" + f"Split: `{a.split}`\n\nValid: {sum(r['valid'] for r in rows)}/{len(rows)}\n", encoding="utf-8")
    return 0
if __name__ == "__main__": raise SystemExit(main())
