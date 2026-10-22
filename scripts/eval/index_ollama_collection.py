"""Index corpus.v1.jsonl into a new, explicitly isolated BGE-M3 collection."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from qdrant_client import AsyncQdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.indexing import index_records


async def ollama_embed(texts: list[str], *, base_url: str, model: str) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post(f"{base_url.rstrip('/')}/api/embed", json={"model": model, "input": texts})
        response.raise_for_status()
        vectors = response.json().get("embeddings")
    if not isinstance(vectors, list):
        raise RuntimeError("respuesta de Ollama sin embeddings")
    return vectors


def load_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main(args: argparse.Namespace) -> int:
    records = load_records(args.corpus)
    client = AsyncQdrantClient(url=args.qdrant_url)
    started = time.perf_counter()
    try:
        report = await index_records(
            records,
            collection=args.collection,
            model=args.model,
            embed=lambda texts: ollama_embed(texts, base_url=args.ollama_url, model=args.model),
            qdrant=client,
            recreate=args.recreate,
        )
    finally:
        await client.close()
    output = {**report.__dict__, "wall_ms": round((time.perf_counter() - started) * 1000)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/eval/retrieval/corpus.v1.jsonl"))
    parser.add_argument("--collection", default="tutor_eval_bge_m3_v1")
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--output", type=Path, default=Path("data/eval/runs/bge_m3_index.json"))
    parser.add_argument("--recreate", action="store_true")
    return asyncio.run(main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(cli())
