"""Deterministic Spanish sparse retrieval and dense/sparse RRF fusion."""
from __future__ import annotations
import math, re, unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from .runner import RankedCandidate

_TOKEN = re.compile(r"[\wáéíóúüñ]+", re.UNICODE)

def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return [token for token in _TOKEN.findall(normalized) if len(token) > 1]

@dataclass(frozen=True)
class CorpusDocument:
    document_id: str
    content: str
    metadata: Mapping[str, Any]

class BM25Index:
    def __init__(self, documents: Sequence[CorpusDocument], *, k1: float = 1.5, b: float = .75) -> None:
        self.documents = tuple(documents); self.k1, self.b = k1, b
        self.term_freqs = [self._tf(tokenize(doc.content)) for doc in self.documents]
        self.avgdl = sum(sum(tf.values()) for tf in self.term_freqs) / max(len(self.documents), 1)
        df: dict[str, int] = {}
        for tf in self.term_freqs:
            for term in tf: df[term] = df.get(term, 0) + 1
        self.idf = {term: math.log(1 + (len(self.documents) - count + .5) / (count + .5)) for term, count in df.items()}

    @staticmethod
    def _tf(tokens: Iterable[str]) -> dict[str, int]:
        tf: dict[str, int] = {}
        for token in tokens: tf[token] = tf.get(token, 0) + 1
        return tf

    def search(self, query: str, *, limit: int = 5) -> list[RankedCandidate]:
        qtf = self._tf(tokenize(query)); scored = []
        for doc, tf in zip(self.documents, self.term_freqs, strict=True):
            dl = sum(tf.values()); score = 0.0
            for term in qtf:
                if term not in tf: continue
                score += self.idf.get(term, 0.0) * tf[term] * (self.k1 + 1) / (tf[term] + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1)))
            if score > 0: scored.append(RankedCandidate(doc.document_id, score, {**dict(doc.metadata), "sparse_score": score}))
        return sorted(scored, key=lambda item: (-item.score, item.candidate_id))[:limit]

def rrf_fuse(dense: Sequence[RankedCandidate], sparse: Sequence[RankedCandidate], *, limit: int = 5, rank_constant: int = 60) -> list[RankedCandidate]:
    dense_by_id = {item.candidate_id: item for item in dense}; sparse_by_id = {item.candidate_id: item for item in sparse}
    fused: dict[str, float] = {}
    for rank, item in enumerate(dense, 1): fused[item.candidate_id] = fused.get(item.candidate_id, 0) + 1 / (rank_constant + rank)
    for rank, item in enumerate(sparse, 1): fused[item.candidate_id] = fused.get(item.candidate_id, 0) + 1 / (rank_constant + rank)
    output = []
    for identifier, score in sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]:
        d, s = dense_by_id.get(identifier), sparse_by_id.get(identifier)
        metadata = {**dict((d or s).metadata), "dense_score": None if d is None else d.score, "sparse_score": None if s is None else s.score, "fused_score": score}
        output.append(RankedCandidate(identifier, score, metadata))
    return output

class HybridBackend:
    def __init__(self, dense_backend: Any, sparse_index: BM25Index, *, candidate_limit: int = 20) -> None:
        self.dense_backend, self.sparse_index, self.candidate_limit = dense_backend, sparse_index, candidate_limit

    async def search(self, query: str, *, limit: int, score_threshold: float | None):
        dense = self.dense_backend.search(query, limit=self.candidate_limit, score_threshold=score_threshold)
        if hasattr(dense, "__await__"): dense = await dense
        sparse = self.sparse_index.search(query, limit=self.candidate_limit)
        return rrf_fuse(dense, sparse, limit=limit)

class SparseBackend:
    def __init__(self, index: BM25Index) -> None: self.index = index
    def search(self, query: str, *, limit: int, score_threshold: float | None): return self.index.search(query, limit=limit)
