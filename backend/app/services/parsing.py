"""Turn uploaded files into clean text and overlapping, page-aware chunks for retrieval."""

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

SUPPORTED_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
    "text/x-markdown": "text",
}
SUPPORTED_EXTENSIONS = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}


class UnsupportedDocument(ValueError):
    """Raised for files we cannot read. Not retryable."""


@dataclass
class ParsedDocument:
    text: str
    page_count: int
    page_offsets: list[int]  # char offset where each page starts


@dataclass
class TextChunk:
    idx: int
    text: str
    start_char: int
    end_char: int
    page: int | None


def detect_content_type(filename: str, declared: str | None) -> str:
    if declared in SUPPORTED_TYPES:
        return declared
    lower = filename.lower()
    for ext, ctype in SUPPORTED_EXTENSIONS.items():
        if lower.endswith(ext):
            return ctype
    raise UnsupportedDocument(f"Unsupported file type for {filename!r}. Upload PDF, TXT or Markdown.")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_document(data: bytes, content_type: str) -> ParsedDocument:
    kind = SUPPORTED_TYPES.get(content_type)
    if kind == "text":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        text = _normalize(text)
        return ParsedDocument(text=text, page_count=1, page_offsets=[0])
    if kind == "pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:  # pypdf raises a variety of errors for corrupt files
            raise UnsupportedDocument(f"Could not read PDF: {exc}") from exc
        if reader.is_encrypted:
            raise UnsupportedDocument("Encrypted PDFs are not supported.")
        parts: list[str] = []
        offsets: list[int] = []
        cursor = 0
        for page in reader.pages:
            page_text = _normalize(page.extract_text() or "")
            offsets.append(cursor)
            parts.append(page_text)
            cursor += len(page_text) + 2
        text = "\n\n".join(parts)
        if len(text.strip()) < 20:
            raise UnsupportedDocument("No extractable text found (scanned PDFs need OCR).")
        return ParsedDocument(text=text, page_count=len(reader.pages), page_offsets=offsets)
    raise UnsupportedDocument(f"Unsupported content type {content_type!r}")


def _page_for(offset: int, page_offsets: list[int]) -> int:
    page = 1
    for i, start in enumerate(page_offsets):
        if offset >= start:
            page = i + 1
    return page


def chunk_text(parsed: ParsedDocument, size: int = 1200, overlap: int = 200) -> list[TextChunk]:
    """Split on paragraph boundaries where possible, keeping chunks near ``size`` chars with overlap."""
    text = parsed.text
    chunks: list[TextChunk] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # Prefer to break at a paragraph, then a sentence, then a space.
            window = text[start:end]
            for sep in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(sep)
                if cut > size * 0.5:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    idx=len(chunks),
                    text=piece,
                    start_char=start,
                    end_char=end,
                    page=_page_for((start + end) // 2, parsed.page_offsets) if parsed.page_count > 1 else None,
                )
            )
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks
