from __future__ import annotations

import io
from dataclasses import dataclass

from .exceptions import ValidationError
from .security import ValidatedUpload


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    page_count: int
    warnings: list[str]


def extract_document(upload: ValidatedUpload, max_pages: int = 100) -> ExtractedDocument:
    if upload.media_type == "text/plain":
        return ExtractedDocument(upload.content.decode("utf-8"), 1, [])
    if upload.media_type != "application/pdf":
        return ExtractedDocument("", 0, ["asset stored; no text extractor for this media type"])
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValidationError("PDF extraction requires the pypdf project dependency") from error
    try:
        reader = PdfReader(io.BytesIO(upload.content), strict=True)
    except Exception as error:
        raise ValidationError("PDF could not be parsed safely") from error
    if len(reader.pages) > max_pages:
        raise ValidationError(f"PDF exceeds the {max_pages}-page processing limit")
    parts: list[str] = []
    warnings: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
            parts.append(f"[Page {index + 1}]\n{text}")
        except Exception:
            warnings.append(f"page {index + 1} could not be extracted")
    if not any(part.strip() for part in parts):
        warnings.append("no embedded text found; configure an isolated OCR worker")
    return ExtractedDocument("\n\n".join(parts), len(reader.pages), warnings)
