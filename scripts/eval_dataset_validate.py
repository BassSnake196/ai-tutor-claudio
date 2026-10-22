"""Validate the versioned retrieval seed without contacting services."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.chunker import chunk_text

DEFAULT_DIR = ROOT / "data" / "eval" / "retrieval"
ALLOWED_SPLITS = {"calibration", "dev", "test"}
ALLOWED_POLICIES = {"UPLOADED_ONLY", "LOCAL_FIRST", "EXTERNAL_ALLOWED", "NO_SOURCES"}
ALLOWED_ANSWERABILITY = {"answerable", "unanswerable", "ambiguous"}
ALLOWED_STATUS = {"seed_verified", "needs_human_curation"}
ALLOWED_CATEGORIES = {"CONCEPTS", "PROGRESSION", "DIDACTICS", "ASSESSMENT", "CURRICULUM_REQUIREMENTS"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate(dataset_dir: Path) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    manifest_path = dataset_dir / "manifest.json"
    query_path = dataset_dir / "dataset.v1.jsonl"
    if not manifest_path.exists():
        return [f"missing: {manifest_path}"], {}
    if not query_path.exists():
        return [f"missing: {query_path}"], {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_query_hash = sha256_file(query_path)
    if manifest.get("query_file_sha256") != actual_query_hash:
        fail(errors, "query_file_sha256 no coincide (ejecuta --refresh-hashes).")

    known_chunks: set[str] = set()
    known_sources: set[str] = set()
    snapshot_path = dataset_dir / str(manifest.get("corpus_snapshot", ""))
    if not snapshot_path.exists():
        fail(errors, f"snapshot de corpus ausente: {snapshot_path}")
    else:
        actual_snapshot_hash = sha256_file(snapshot_path)
        if manifest.get("corpus_snapshot_sha256") != actual_snapshot_hash:
            fail(errors, "corpus_snapshot_sha256 no coincide (ejecuta --refresh-hashes).")
        for line_number, line in enumerate(snapshot_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
                payload = record["payload"]
                chunk_id = str(payload["chunk_id"])
                source_id = str(payload["source_id"])
                if chunk_id in known_chunks:
                    fail(errors, f"snapshot línea {line_number}: chunk_id duplicado: {chunk_id}")
                known_chunks.add(chunk_id)
                known_sources.add(source_id)
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                fail(errors, f"snapshot línea {line_number}: registro inválido ({exc})")

    cases: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(query_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            fail(errors, f"línea {line_number}: JSON inválido ({exc})")
            continue
        cases.append(case)
        query_id = case.get("query_id")
        if not isinstance(query_id, str) or not query_id or query_id in seen_ids:
            fail(errors, f"línea {line_number}: query_id ausente o duplicado")
        seen_ids.add(str(query_id))
        if case.get("split") not in ALLOWED_SPLITS:
            fail(errors, f"{query_id}: split inválido")
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            fail(errors, f"{query_id}: query vacía")
        if case.get("source_policy") not in ALLOWED_POLICIES:
            fail(errors, f"{query_id}: source_policy inválida")
        if case.get("answerability") not in ALLOWED_ANSWERABILITY:
            fail(errors, f"{query_id}: answerability inválida")
        if case.get("annotation_status") not in ALLOWED_STATUS:
            fail(errors, f"{query_id}: annotation_status inválido")
        if not isinstance(case.get("expected_categories"), list) or not set(case["expected_categories"]) <= ALLOWED_CATEGORIES:
            fail(errors, f"{query_id}: categorías inválidas")
        source_ids = case.get("source_ids", [])
        if not isinstance(source_ids, list):
            fail(errors, f"{query_id}: source_ids debe ser lista")
        elif case.get("source_policy") == "UPLOADED_ONLY" and not source_ids:
            fail(errors, f"{query_id}: UPLOADED_ONLY requiere source_ids")
        elif any(source not in known_sources for source in source_ids):
            fail(errors, f"{query_id}: source_id no declarado en corpus")
        qrels = case.get("qrels")
        if not isinstance(qrels, dict):
            fail(errors, f"{query_id}: qrels debe ser objeto")
        else:
            for chunk_id, grade in qrels.items():
                if chunk_id not in known_chunks:
                    fail(errors, f"{query_id}: qrel apunta a chunk inexistente: {chunk_id}")
                if case.get("source_policy") == "UPLOADED_ONLY" and not any(
                    chunk_id.startswith(f"{source_id}:") for source_id in source_ids
                ):
                    fail(errors, f"{query_id}: qrel fuga del filtro UPLOADED_ONLY: {chunk_id}")
                if grade not in {0, 1, 2}:
                    fail(errors, f"{query_id}: grado qrel fuera de 0/1/2")
            if case.get("answerability") == "unanswerable" and qrels:
                fail(errors, f"{query_id}: unanswerable no debe tener qrels positivos")
    counts = {split: sum(case.get("split") == split for case in cases) for split in ALLOWED_SPLITS}
    summary = {"queries": len(cases), "splits": counts, "known_chunks": len(known_chunks), "query_sha256": actual_query_hash}
    return errors, summary


def refresh_hashes(dataset_dir: Path) -> None:
    manifest_path = dataset_dir / "manifest.json"
    query_path = dataset_dir / "dataset.v1.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["query_file_sha256"] = sha256_file(query_path)
    snapshot_path = dataset_dir / str(manifest.get("corpus_snapshot", ""))
    if snapshot_path.exists():
        manifest["corpus_snapshot_sha256"] = sha256_file(snapshot_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_live_corpus(output_path: Path) -> None:
    """Export payloads only; network access is intentionally explicit and opt-in."""
    import asyncio
    from qdrant_client import AsyncQdrantClient

    async def collect() -> list[dict[str, object]]:
        client = AsyncQdrantClient(url="http://localhost:6333")
        items: list[dict[str, object]] = []
        offset = None
        try:
            while True:
                points, offset = await client.scroll(
                    collection_name="tutor_documents",
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                items.extend({"point_id": str(point.id), "payload": dict(point.payload or {})} for point in points)
                if offset is None:
                    return items
        finally:
            await client.close()

    records = asyncio.run(collect())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in sorted(records, key=lambda item: str(item["payload"].get("chunk_id", ""))):
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--refresh-hashes", action="store_true")
    parser.add_argument("--export-live-corpus", type=Path)
    args = parser.parse_args()
    if args.export_live_corpus:
        export_live_corpus(args.export_live_corpus)
        print(f"exported {args.export_live_corpus}")
        return 0
    if args.refresh_hashes:
        refresh_hashes(args.dataset_dir)
    errors, summary = validate(args.dataset_dir)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(json.dumps({"status": "valid", **summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
