from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    content: str
    index: int


def chunk_text(text: str, *, source_id: str, chunk_size: int = 1_000, overlap: int = 150) -> list[TextChunk]:
    """Create deterministic, overlapping chunks without splitting words where possible."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size debe ser positivo y overlap menor que chunk_size.")

    normalized = " ".join(text.split())
    if not normalized:
        return []

    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary

        content = normalized[start:end].strip()
        index = len(chunks)
        digest = sha256(f"{source_id}:{index}:{content}".encode()).hexdigest()[:16]
        chunks.append(TextChunk(chunk_id=f"{source_id}:{digest}", content=content, index=index))
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)

    return chunks
