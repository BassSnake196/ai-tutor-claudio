"""CLI for the isolated runner. No live backend is imported or executed."""
from __future__ import annotations
import argparse, asyncio, json, sys
from pathlib import Path
# Make direct ``python scripts/eval/...`` execution independent of the caller's PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.reporting import write_report
from evals.runner import RetrievalRunner, RankedCandidate, case_from_mapping

class JsonFakeBackend:
    def __init__(self, mapping): self.mapping = mapping
    def search(self, query, *, limit, score_threshold): return self.mapping.get(query, [])

def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated retrieval evaluation")
    parser.add_argument("--mode", choices=("fake", "qdrant"), required=True, help="explicit backend mode")
    parser.add_argument("--cases", type=Path, required=True, help="JSONL cases file")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--model", default="fake")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--split", choices=("calibration", "dev", "test"), default="calibration")
    parser.add_argument("--allow-test", action="store_true", help="required to run sealed test split")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    args = parser.parse_args()
    if args.split == "test" and not args.allow_test: parser.error("test split requires --allow-test")
    rows = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("split", "calibration") == args.split]
    cases = [case_from_mapping(row) for row in rows]
    if args.mode == "fake":
        backend = JsonFakeBackend({item["query"]: item.get("candidates", []) for item in rows})
    else:
        from evals.backends import OllamaQdrantBackend
        backend = OllamaQdrantBackend(qdrant_url=args.qdrant_url, collection=args.collection, ollama_url=args.ollama_url, embedding_model=args.embedding_model)
    runner = RetrievalRunner(backend, collection=args.collection, model=args.model if args.mode == "fake" else args.embedding_model, k=args.k, threshold=args.threshold, seed=args.seed)
    manifest, results = asyncio.run(runner.run(cases))
    paths = write_report(args.output, manifest, results)
    if hasattr(backend, "close"): asyncio.run(backend.close())
    print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False))
    return 0

if __name__ == "__main__": raise SystemExit(main())
