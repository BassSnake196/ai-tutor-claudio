"""Run sparse-only, dense-only and RRF retrieval on calibration/dev JSONL cases."""
from __future__ import annotations
import argparse, asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.backends import OllamaQdrantBackend
from evals.dataset import load_dataset
from evals.hybrid import BM25Index, CorpusDocument, HybridBackend, SparseBackend
from evals.reporting import write_report
from evals.runner import RetrievalCase, RetrievalRunner

def load_corpus(path: Path) -> BM25Index:
    docs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        row = json.loads(line); payload = row.get("payload", row)
        docs.append(CorpusDocument(str(payload.get("chunk_id", row.get("point_id"))), str(payload.get("content", "")), payload))
    if not docs: raise ValueError("corpus is empty")
    return BM25Index(docs)

async def main_async(args) -> int:
    query_cases = load_dataset(args.cases, include_test=args.split == "test")
    if args.split == "test" and not args.allow_test:
        raise ValueError("test split requires --allow-test")
    query_cases = [c for c in query_cases if c.split == args.split]
    cases = [RetrievalCase(c.query_id, c.query, tuple(c.relevant_ids), {"allowed_source_ids": c.source_ids}, c.answerable, c.qrels) for c in query_cases]
    sparse = SparseBackend(load_corpus(args.corpus)); dense = OllamaQdrantBackend(qdrant_url=args.qdrant_url, collection=args.collection, ollama_url=args.ollama_url, embedding_model=args.embedding_model)
    try:
        backends = {"sparse": sparse, "dense": dense, "hybrid": HybridBackend(dense, sparse.index)}
        summary = {}
        for name, backend in backends.items():
            manifest, results = await RetrievalRunner(backend, collection=args.collection, model=args.embedding_model, k=args.k, threshold=args.threshold, config={"mode": name, "rrf_k": args.rrf_k}, seed=args.seed).run(cases, run_id=f"{name}_{args.split}_k{args.k}")
            paths = write_report(args.output / name, manifest, results); summary[name] = {"report": str(paths["markdown"]), "metrics": manifest.get("metrics", {})}
        (args.output / "comparison.json").write_text(json.dumps({"split": args.split, "runs": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.output / "comparison.md").write_text("# Hybrid comparison\n\n" + "\n".join(f"- **{name}**: Recall={item['metrics'].get('recall_at_k')}, MRR={item['metrics'].get('mrr_at_k')}, p95={item['metrics'].get('latency_p95_ms')} ms" for name, item in summary.items()), encoding="utf-8")
    finally: await dense.close()
    return 0

def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate sparse, dense and RRF retrieval")
    p.add_argument("--cases", type=Path, required=True); p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True); p.add_argument("--collection", required=True)
    p.add_argument("--split", choices=("calibration", "dev", "test"), default="calibration"); p.add_argument("--allow-test", action="store_true", help="required to run sealed test split"); p.add_argument("--qdrant-url", default="http://localhost:6333")
    p.add_argument("--ollama-url", default="http://localhost:11434"); p.add_argument("--embedding-model", default="nomic-embed-text")
    p.add_argument("--k", type=int, default=5); p.add_argument("--threshold", type=float, default=None); p.add_argument("--rrf-k", type=int, default=60); p.add_argument("--seed", type=int, default=0)
    return asyncio.run(main_async(p.parse_args()))
if __name__ == "__main__": raise SystemExit(main())
