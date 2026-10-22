import asyncio

import pytest

from evals.indexing import index_records, validate_destination, validate_embeddings


def test_destination_must_be_isolated() -> None:
    with pytest.raises(ValueError):
        validate_destination("tutor_documents")
    with pytest.raises(ValueError):
        validate_destination("anything")


def test_embeddings_reject_nan_and_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        validate_embeddings([[1.0, float("nan")]])
    with pytest.raises(ValueError):
        validate_embeddings([[1.0, 2.0], [1.0]])


def test_fake_index_validates_count_and_payload() -> None:
    class Collection:
        def __init__(self): self.points = []
        async def collection_exists(self, name): return False
        async def create_collection(self, **kwargs): self.config = kwargs
        async def upsert(self, **kwargs): self.points.extend(kwargs["points"])
        async def count(self, **kwargs): return type("Count", (), {"count": len(self.points)})()

    records = [{"point_id": "p1", "payload": {"chunk_id": "source:1", "source_id": "source", "content": "texto"}}]
    async def embed(texts): return [[0.1, 0.2, 0.3] for _ in texts]
    report = asyncio.run(index_records(records, collection="tutor_eval_bge_m3_test", model="fake", embed=embed, qdrant=Collection()))
    assert report.point_count == 1
    assert report.vector_dimension == 3
