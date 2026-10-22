"""Canonical, injection-resistant serialization of retrieved evidence."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.source_resolution import EvidenceBundle


def _escape_json_delimiters(value: str) -> str:
    """Escape markup delimiters while retaining readable, non-base64 text."""
    return value.replace("<", "\\u003c").replace(">", "\\u003e")


def serialize_evidence(evidence: EvidenceBundle | None) -> str:
    """Return canonical JSON in a fixed container safe for untrusted chunks.

    JSON escaping protects quotes/backslashes; explicitly escaping angle brackets
    prevents a chunk from manufacturing ``</EVIDENCE_JSON>`` or similar markup.
    """
    payload: dict[str, Any] = {
        "coverage": evidence.coverage.model_dump(mode="json") if evidence else None,
        "gaps": list(evidence.gaps) if evidence else [],
        "contradictions": list(evidence.contradictions) if evidence else [],
        "chunks": [
            {
                "category": chunk.category.value,
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "fragment_reference": chunk.fragment_reference,
                "metadata": chunk.metadata.model_dump(mode="json"),
                "score": chunk.score,
                "stage": chunk.stage.value,
            }
            for chunk in (evidence.chunks if evidence else [])
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<EVIDENCE_JSON>{_escape_json_delimiters(canonical)}</EVIDENCE_JSON>"
