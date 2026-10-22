"""Experimental lazy reranking primitives; production retrieval is untouched."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class RerankerScorer(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> Sequence[float]: ...


@dataclass(frozen=True)
class RerankedCandidate:
    candidate_id: str
    retrieval_score: float
    rerank_score: float
    metadata: dict[str, Any]


class FakeRerankerScorer:
    """Deterministic lexical scorer used for tests and offline smoke runs."""

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        query_terms = set(query.casefold().split())
        return [sum(term in document.casefold().split() for term in query_terms) / max(len(query_terms), 1) for document in documents]


class TransformersCrossEncoderScorer:
    """Explicit SciPy-free scorer for exactly the BGE reranker checkpoint."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", *, batch_size: int = 4, max_length: int = 512) -> None:
        if model_name != "BAAI/bge-reranker-v2-m3":
            raise ValueError("only BAAI/bge-reranker-v2-m3 is permitted for this experiment")
        if batch_size < 1 or max_length < 8:
            raise ValueError("batch_size and max_length must be positive")
        self.model_name, self.batch_size, self.max_length = model_name, batch_size, max_length
        self._tokenizer: Any = None
        self._model: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name).to("cpu")
        self._model.eval()

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        self._load()
        import torch
        scores: list[float] = []
        for start in range(0, len(documents), self.batch_size):
            batch = documents[start : start + self.batch_size]
            encoded = self._tokenizer([query] * len(batch), list(batch), padding=True, truncation=True, max_length=self.max_length, return_tensors="pt")
            with torch.no_grad():
                logits = self._model(**encoded).logits
            scores.extend(float(value) for value in logits.reshape(-1).cpu().tolist())
        return scores


class LazyCrossEncoderReranker:
    """Load sentence-transformers only on first real scoring call."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", *, scorer: RerankerScorer | None = None, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._scorer = scorer
        self._model: Any = None
        self.load_error: str | None = None

    def _get_scorer(self) -> RerankerScorer:
        if self._scorer is not None:
            return self._scorer
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name, device=self.device)
            except Exception as exc:
                self.load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(f"reranker deferred/unavailable: {self.load_error}") from exc
        return self._model

    @staticmethod
    def _fields(candidate: Any) -> tuple[str, float, dict[str, Any]]:
        if isinstance(candidate, dict):
            # Evaluation exports use ``result_id`` and keep source/content at
            # the top level; production adapters may use ``candidate_id`` and
            # a nested metadata object. Normalize both shapes without losing
            # provenance required by the metrics.
            nested = dict(candidate.get("metadata", {}) or {})
            metadata = {key: value for key, value in candidate.items() if key not in {"candidate_id", "result_id", "id", "chunk_id", "score", "metadata"}}
            metadata.update(nested)
            identifier = candidate.get("candidate_id", candidate.get("result_id", candidate.get("id", candidate.get("chunk_id"))))
            return str(identifier), float(candidate.get("score", 0.0)), metadata
        metadata = dict(getattr(candidate, "metadata", {}) or {})
        return str(getattr(candidate, "candidate_id", getattr(candidate, "chunk_id", getattr(candidate, "id", "")))), float(getattr(candidate, "score", 0.0)), metadata

    def rank(self, query: str, candidates: Sequence[Any], *, top_k: int) -> list[RerankedCandidate]:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        unique: list[tuple[str, float, dict[str, Any], Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            identifier, retrieval_score, metadata = self._fields(candidate)
            if identifier in seen:
                continue
            seen.add(identifier)
            unique.append((identifier, retrieval_score, metadata, candidate))
        if not unique:
            return []
        documents = [str(item[2].get("content", item[0])) for item in unique]
        scores = list(self._get_scorer().score(query, documents))
        if len(scores) != len(unique):
            raise ValueError("reranker scorer returned the wrong number of scores")
        ranked = [RerankedCandidate(item[0], item[1], float(score), item[2]) for item, score in zip(unique, scores, strict=True)]
        return sorted(ranked, key=lambda item: (-item.rerank_score, -item.retrieval_score, item.candidate_id))[:top_k]


class RerankedBackend:
    """RetrievalRunner-compatible adapter: fetch top-N, then return reranked top-k."""

    def __init__(self, backend: Any, reranker: LazyCrossEncoderReranker, *, candidate_limit: int = 20, top_k: int = 5) -> None:
        if candidate_limit < top_k or top_k < 1:
            raise ValueError("candidate_limit must be >= top_k >= 1")
        self.backend, self.reranker, self.candidate_limit, self.top_k = backend, reranker, candidate_limit, top_k

    async def search(self, query: str, *, limit: int, score_threshold: float | None) -> list[RerankedCandidate]:
        candidates = self.backend.search(query, limit=self.candidate_limit, score_threshold=score_threshold)
        if hasattr(candidates, "__await__"):
            candidates = await candidates
        return self.reranker.rank(query, list(candidates), top_k=min(limit, self.top_k))
