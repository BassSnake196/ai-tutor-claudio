"""Calibrate k/threshold offline; never embeds or opens the sealed test split."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.calibration import calibrate, load_raw, recommend, write_calibration
from evals.dataset import load_dataset

def main() -> int:
    p = argparse.ArgumentParser(description="Calibrate retrieval thresholds from raw top-20 JSON")
    p.add_argument("--run", type=Path, required=True); p.add_argument("--dataset", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--split", choices=("calibration", "dev"), default="calibration")
    a = p.parse_args(); manifest, queries = load_raw(a.run); cases = [c for c in load_dataset(a.dataset) if c.split == a.split]
    rows = calibrate(manifest, queries, cases); paths = write_calibration(a.output, rows, recommend(rows)); print(json.dumps({k: str(v) for k, v in paths.items()})); return 0
if __name__ == "__main__": raise SystemExit(main())
