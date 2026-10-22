from app.agents.critic_agent import GroundingAuditor
from app.schemas.responses import Citation, GroundingStatus


def test_grounding_is_supported_when_citation_was_retrieved() -> None:
    citation = Citation(source_id="doc-1", fragment_reference="página 1")

    result = GroundingAuditor().assess([citation], {"doc-1"})

    assert result is GroundingStatus.SUPPORTED


def test_grounding_abstains_without_citations() -> None:
    assert GroundingAuditor().assess([], {"doc-1"}) is GroundingStatus.INSUFFICIENT_CONTEXT
