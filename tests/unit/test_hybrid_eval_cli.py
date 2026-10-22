import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "eval" / "run_hybrid_eval.py"
CASES = ROOT / "data" / "eval" / "retrieval" / "dataset.v1.jsonl"


def test_hybrid_runner_blocks_sealed_test_without_explicit_flag(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--cases", str(CASES), "--corpus", str(ROOT / "data/eval/retrieval/corpus.v1.jsonl"), "--output", str(tmp_path), "--collection", "tutor_eval_nomic_v1", "--split", "test"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "test split requires --allow-test" in result.stderr
