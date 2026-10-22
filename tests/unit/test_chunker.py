from app.rag.chunker import chunk_text


def test_chunker_returns_deterministic_nonempty_chunks() -> None:
    text = "Una frase educativa. " * 100

    first = chunk_text(text, source_id="course-1", chunk_size=100, overlap=20)
    second = chunk_text(text, source_id="course-1", chunk_size=100, overlap=20)

    assert len(first) > 1
    assert first == second
    assert all(chunk.content for chunk in first)
