"""Join raw top-k retrieval runs with the immutable corpus snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def load_corpus(path: Path) -> dict[str, dict]:
    corpus = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        payload = row.get("payload", row)
        identifier = payload.get("chunk_id")
        if not identifier or not payload.get("content"):
            raise ValueError("corpus row lacks chunk_id/content")
        corpus[str(identifier)] = payload
    return corpus


def export(run_paths: list[Path], corpus_path: Path, output: Path) -> dict[str, int]:
    corpus = load_corpus(corpus_path)
    queries: dict[str, dict] = {}
    for run_path in run_paths:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        for query in run.get("queries", []):
            query_id = str(query["case_id"])
            if "-test-" in query_id:
                continue
            target = queries.setdefault(query_id, {"query_id": query_id, "query": query["query"], "candidates": []})
            known = {item["result_id"] for item in target["candidates"]}
            for candidate in query.get("candidates", []):
                result_id = str(candidate["candidate_id"])
                if result_id in known:
                    continue
                payload = corpus.get(result_id)
                if payload is None or not payload.get("content"):
                    raise ValueError(f"missing corpus content for candidate {result_id}")
                target["candidates"].append({"result_id": result_id, "score": float(candidate.get("score", 0.0)), "source_id": payload.get("source_id"), "content": payload["content"]})
                known.add(result_id)
            target["candidates"] = target["candidates"][:20]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in queries.values()) + "\n", encoding="utf-8")
    return {"queries": len(queries), "candidates": sum(len(row["candidates"]) for row in queries.values())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True, type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("data/eval/retrieval/corpus.v1.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.corpus, args.output)))


if __name__ == "__main__":
    main()
