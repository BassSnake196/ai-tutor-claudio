"""Immutable fingerprints for curriculum evaluation provenance."""
from __future__ import annotations
import hashlib, json
from typing import Any, Mapping

def fingerprint(*, prompt: str, model: str, config: Mapping[str, Any]) -> dict[str, Any]:
    payload = {"prompt": prompt, "model": model, "config": dict(config)}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(), "model": model, "config": dict(config), "run_hash": hashlib.sha256(canonical.encode()).hexdigest()}
