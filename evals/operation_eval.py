"""Provider operation telemetry aggregation without prompt or secret content."""
from __future__ import annotations
from collections import Counter
from typing import Any, Mapping, Sequence
from .metrics import percentile

def summarize(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latencies = [float(e["latency_ms"]) for e in events if e.get("latency_ms") is not None]
    status = Counter(str(e.get("status", "unknown")) for e in events)
    return {"calls": len(events), "fallbacks": sum(bool(e.get("fallback")) for e in events), "repairs": sum(bool(e.get("repair")) for e in events), "prompt_tokens": sum(int(e.get("prompt_tokens", 0) or 0) for e in events), "output_tokens": sum(int(e.get("output_tokens", 0) or 0) for e in events), "total_tokens": sum(int(e.get("total_tokens", 0) or 0) for e in events), "latency_p50_ms": percentile(latencies, 50), "latency_p95_ms": percentile(latencies, 95), "statuses": dict(status), "errors": [str(e["error_type"]) for e in events if e.get("error_type")]}
