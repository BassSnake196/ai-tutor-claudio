"""Non-destructive, idempotent migration of Qdrant payloads to schema v2.

This script never deletes points or recreates a collection. By default it creates a
Qdrant snapshot before writing. Use ``--dry-run`` to inspect the planned updates.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PayloadSchemaType

from app.rag.source_metadata import (
    ACTIVE_STATUS,
    DEFAULT_LIBRARY_ID,
    PAYLOAD_SCHEMA_VERSION,
    content_hash,
    document_id,
    utc_now_iso,
)
from app.rag.vector_store import PAYLOAD_KEYWORD_INDEXES


@dataclass(frozen=True)
class MigrationReport:
    collection_name: str
    points_before: int
    points_after: int
    updated_points: int
    unchanged_points: int
    dry_run: bool
    snapshot_name: str | None = None


async def migrate_payload_v2(
    client: AsyncQdrantClient,
    *,
    collection_name: str,
    default_library_id: str = DEFAULT_LIBRARY_ID,
    dry_run: bool = False,
    create_snapshot: bool = True,
) -> MigrationReport:
    if not await client.collection_exists(collection_name):
        raise ValueError(f"La colección '{collection_name}' no existe.")

    records = await _scroll_all(client, collection_name)
    ids_before = {str(record.id) for record in records}
    document_hashes = _legacy_document_hashes(records)
    migration_timestamp = utc_now_iso()
    updates: list[tuple[Any, dict[str, Any]]] = []

    for record in records:
        payload = dict(record.payload or {})
        source_id = _source_id(payload, record.id)
        document_hash = str(payload.get("document_hash") or document_hashes[source_id])
        desired = {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "source_id": source_id,
            "document_id": str(
                payload.get("document_id")
                or document_id(source_id=source_id, document_hash=document_hash)
            ),
            "library_id": str(payload.get("library_id") or default_library_id),
            "title": str(payload.get("title") or source_id),
            "source_type": str(payload.get("source_type") or "unknown"),
            "language": str(payload.get("language") or "und"),
            "chunk_index": int(payload.get("chunk_index", 0)),
            "content_hash": str(payload.get("content_hash") or content_hash(str(payload.get("content", "")))),
            "document_hash": document_hash,
            "ingested_at": str(payload.get("ingested_at") or migration_timestamp),
            "status": str(payload.get("status") or ACTIVE_STATUS),
        }
        missing_or_outdated = {
            key: value for key, value in desired.items() if payload.get(key) != value
        }
        if missing_or_outdated:
            updates.append((record.id, missing_or_outdated))

    snapshot_name: str | None = None
    if updates and not dry_run:
        if create_snapshot:
            snapshot = await client.create_snapshot(collection_name=collection_name, wait=True)
            snapshot_name = getattr(snapshot, "name", None)
        for point_id, payload_update in updates:
            await client.set_payload(
                collection_name=collection_name,
                payload=payload_update,
                points=[point_id],
                wait=True,
            )
    if not dry_run:
        collection = await client.get_collection(collection_name)
        indexed_fields = set((collection.payload_schema or {}).keys())
        for field_name in PAYLOAD_KEYWORD_INDEXES:
            if field_name in indexed_fields:
                continue
            await client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )

    records_after = records if dry_run else await _scroll_all(client, collection_name)
    ids_after = {str(record.id) for record in records_after}
    if ids_after != ids_before:
        raise RuntimeError("La verificación falló: los IDs cambiaron durante la migración.")

    return MigrationReport(
        collection_name=collection_name,
        points_before=len(ids_before),
        points_after=len(ids_after),
        updated_points=len(updates),
        unchanged_points=len(records) - len(updates),
        dry_run=dry_run,
        snapshot_name=snapshot_name,
    )


async def _scroll_all(client: AsyncQdrantClient, collection_name: str) -> list[Any]:
    records: list[Any] = []
    offset: Any = None
    while True:
        page, next_offset = await client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        records.extend(page)
        if next_offset is None:
            return records
        offset = next_offset


def _source_id(payload: dict[str, Any], point_id: Any) -> str:
    if payload.get("source_id"):
        return str(payload["source_id"])
    chunk_id = str(payload.get("chunk_id", ""))
    if ":" in chunk_id:
        return chunk_id.split(":", 1)[0]
    return f"legacy-{point_id}"


def _legacy_document_hashes(records: list[Any]) -> dict[str, str]:
    by_source: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for record in records:
        payload = dict(record.payload or {})
        source_id = _source_id(payload, record.id)
        by_source[source_id].append(
            (int(payload.get("chunk_index", 0)), str(payload.get("content", "")))
        )
    return {
        source_id: content_hash("\n".join(content for _, content in sorted(chunks)))
        for source_id, chunks in by_source.items()
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:6333")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--library-id", default=DEFAULT_LIBRARY_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-snapshot", action="store_true")
    args = parser.parse_args()
    client = AsyncQdrantClient(url=args.url, timeout=120)
    try:
        report = await migrate_payload_v2(
            client,
            collection_name=args.collection,
            default_library_id=args.library_id,
            dry_run=args.dry_run,
            create_snapshot=not args.skip_snapshot,
        )
        print(report)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_main())
