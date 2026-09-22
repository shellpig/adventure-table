from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from app.domain.adventure_imports.errors import (
    AdventureImportError,
    ExtractorUnavailableError,
)


@dataclass(frozen=True)
class ExtractionResult:
    normalized_text: str
    sections: tuple[dict[str, object], ...]


def extract_pdf_text(data: bytes) -> ExtractionResult:
    """Extract text and page-based locator sections from PDF bytes."""
    from app.domain.adventure_imports.service import normalize_source_text
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as exc:
        raise ExtractorUnavailableError(f"pypdf is not installed: {exc}") from exc

    try:
        reader = PdfReader(BytesIO(data))
    except (PyPdfError, ValueError, OSError):
        return ExtractionResult(normalized_text="", sections=())

    page_texts: list[tuple[int, str]] = []
    for page_idx, page in enumerate(reader.pages):
        try:
            raw_text = page.extract_text() or ""
        except (PyPdfError, ValueError, TypeError, KeyError):
            raw_text = ""
        norm_text = normalize_source_text(raw_text).removesuffix("\n")
        if norm_text:
            page_texts.append((page_idx, norm_text))

    if not page_texts:
        return ExtractionResult(normalized_text="", sections=())

    sections: list[dict[str, object]] = []
    parts: list[str] = []
    current_offset = 0
    for page_idx, page_text in page_texts:
        if parts:
            parts.append("\n\n")
            current_offset += 2
        start_offset = current_offset
        parts.append(page_text)
        current_offset += len(page_text)
        end_offset = current_offset
        sections.append(
            {
                "page_index": page_idx,
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )

    parts.append("\n")
    final_text = "".join(parts)
    return ExtractionResult(normalized_text=final_text, sections=tuple(sections))


def extract_docx_text(data: bytes) -> ExtractionResult:
    """Extract text and paragraph/heading locator sections from DOCX bytes."""
    from app.domain.adventure_imports.service import normalize_source_text
    try:
        from docx import Document
        from docx.opc.exceptions import OpcError
    except ImportError as exc:
        raise ExtractorUnavailableError(f"python-docx is not installed: {exc}") from exc

    try:
        doc = Document(BytesIO(data))
    except (OpcError, ValueError, KeyError, OSError):
        return ExtractionResult(normalized_text="", sections=())

    para_items: list[tuple[int, str, int | None]] = []
    heading_counter = 0
    for para_idx, para in enumerate(doc.paragraphs):
        raw_text = para.text or ""
        norm_text = normalize_source_text(raw_text).removesuffix("\n")
        if not norm_text:
            continue
        style_name = para.style.name if para.style is not None else ""
        is_heading = bool(style_name and style_name.lower().startswith("heading"))
        if is_heading:
            h_idx: int | None = heading_counter
            heading_counter += 1
        else:
            h_idx = None
        para_items.append((para_idx, norm_text, h_idx))

    if not para_items:
        return ExtractionResult(normalized_text="", sections=())

    sections: list[dict[str, object]] = []
    parts: list[str] = []
    current_offset = 0
    for para_idx, para_text, h_idx in para_items:
        if parts:
            parts.append("\n\n")
            current_offset += 2
        start_offset = current_offset
        parts.append(para_text)
        current_offset += len(para_text)
        end_offset = current_offset
        sections.append(
            {
                "paragraph_index": para_idx,
                "heading_index": h_idx,
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )

    parts.append("\n")
    final_text = "".join(parts)
    return ExtractionResult(normalized_text=final_text, sections=tuple(sections))


__all__ = [
    "ExtractionResult",
    "ExtractorUnavailableError",
    "extract_docx_text",
    "extract_pdf_text",
]
