from pathlib import Path

from docx import Document
from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    """The ingestion pipeline only accepts a locally stored, supported file type."""


def extract_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)

    suffix = path.suffix.casefold()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    raise UnsupportedDocumentError(f"Formato no soportado: {suffix or 'sin extensión'}")
