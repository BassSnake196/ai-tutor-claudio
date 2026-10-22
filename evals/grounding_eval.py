"""Deterministic citation/provenance checks; semantic entailment is out of scope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


@dataclass(frozen=True)
class GroundingEvaluation:
    invented_citation_ids: tuple[str, ...] = ()
    decorative_citations: tuple[str, ...] = ()
    uncited_claims: tuple[str, ...] = ()
    contradictions_declared: tuple[str, ...] = ()
    entailment_evaluated: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not (
            self.invented_citation_ids
            or self.decorative_citations
            or self.uncited_claims
            or self.contradictions_declared
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "invented_citation_ids": list(self.invented_citation_ids),
            "decorative_citations": list(self.decorative_citations),
            "uncited_claims": list(self.uncited_claims),
            "contradictions_declared": list(self.contradictions_declared),
            "entailment_evaluated": self.entailment_evaluated,
            "warnings": list(self.warnings),
            "passed": self.passed,
        }


def evaluate_citations(
    evidence: Any,
    citations: Iterable[Any],
    *,
    claims: Iterable[Any] | None = None,
) -> GroundingEvaluation:
    """Check exact retrieved fragment/source references and optional claim links.

    ``claims`` may contain strings (all require a citation) or mappings with
    ``text`` and ``citation_fragment_references``. This function checks links,
    not whether text is entailed by a chunk.
    """
    chunks = list(_get(evidence, "chunks", []) or [])
    authorized_fragments = {
        str(_get(chunk, "fragment_reference", "")) for chunk in chunks if _get(chunk, "fragment_reference")
    }
    authorized_sources = {
        str(_get(_get(chunk, "metadata", None), "source_id", ""))
        for chunk in chunks
        if _get(_get(chunk, "metadata", None), "source_id")
    }
    invented: list[str] = []
    decorative: list[str] = []
    for citation in citations:
        source_id = str(_get(citation, "source_id", ""))
        reference = str(_get(citation, "fragment_reference", "") or "")
        if not reference:
            decorative.append(source_id or "<missing-source>")
        elif reference not in authorized_fragments or source_id not in authorized_sources:
            invented.append(reference or source_id or "<empty-citation>")

    uncited: list[str] = []
    for claim in claims or ():
        if isinstance(claim, str):
            uncited.append(claim)
            continue
        text = str(_get(claim, "text", "")).strip()
        references = _get(claim, "citation_fragment_references", ()) or ()
        if text and not list(references):
            uncited.append(text)
    contradictions = tuple(str(item) for item in (_get(evidence, "contradictions", []) or []))
    warnings = (
        "Entailment semántico no evaluado; estas comprobaciones sólo verifican procedencia y enlaces explícitos.",
    )
    return GroundingEvaluation(
        invented_citation_ids=tuple(dict.fromkeys(invented)),
        decorative_citations=tuple(dict.fromkeys(decorative)),
        uncited_claims=tuple(dict.fromkeys(uncited)),
        contradictions_declared=contradictions,
        warnings=warnings,
    )
