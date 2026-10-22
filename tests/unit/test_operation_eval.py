from evals.operation_eval import summarize
from types import SimpleNamespace
import pytest
from google import genai
from app.ai.providers.gemini import GeminiLanguageModel

def test_operation_summary_counts_cost_and_typed_errors():
    result = summarize([{"latency_ms":10,"total_tokens":4,"prompt_tokens":2,"output_tokens":2,"status":"success"}, {"latency_ms":30,"fallback":True,"repair":True,"total_tokens":6,"status":"error","error_type":"TimeoutError"}])
    assert result["calls"] == 2 and result["fallbacks"] == 1 and result["repairs"] == 1
    assert result["total_tokens"] == 10 and result["latency_p95_ms"] == 29
    assert result["errors"] == ["TimeoutError"]

@pytest.mark.asyncio
async def test_summary_counts_real_provider_events(monkeypatch):
    class FakeModels:
        def generate_content(self, *, model, contents):
            if model == "primary": raise TimeoutError("offline")
            return SimpleNamespace(text="ok", usage_metadata=SimpleNamespace(prompt_token_count=2, candidates_token_count=3, total_token_count=5))
    monkeypatch.setattr(genai, "Client", lambda **_: SimpleNamespace(models=FakeModels()))
    provider = GeminiLanguageModel(api_key="test", model="primary", fallback_models=["fallback"])
    await provider.generate_with_usage("x")
    result = summarize(provider.drain_attempt_log())
    assert result["calls"] == 2 and result["fallbacks"] == 1 and result["total_tokens"] == 5
