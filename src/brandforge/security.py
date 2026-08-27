from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePath

from .exceptions import SecurityError

ALLOWED_MEDIA_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all|any|the)\s+(previous|prior|system)\s+instructions?",
        r"reveal\s+(the\s+)?(system prompt|secret|credential|api key)",
        r"upload\s+(?:(?:all|any)\s+)?(?:confidential|private)\s+files?",
        r"upload\s+(?:all|any)\s+files?",
        r"act\s+as\s+(an?\s+)?(administrator|system|developer)",
        r"execute\s+(this\s+)?(command|code|script)",
    )
]


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    media_type: str
    content: bytes
    sha256: str
    size_bytes: int


def sanitize_filename(filename: str) -> str:
    leaf = PurePath(filename).name
    safe = _SAFE_FILENAME.sub("-", leaf).strip(".-")
    if not safe or len(safe) > 120:
        raise SecurityError("filename is invalid")
    return safe


def sniff_media_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    try:
        decoded = content.decode("utf-8")
        if "\x00" not in decoded:
            return "text/plain"
    except UnicodeDecodeError:
        pass
    raise SecurityError("file content is not an allowed media type")


def validate_upload(
    filename: str, content: bytes, declared_media_type: str | None, max_bytes: int
) -> ValidatedUpload:
    if not content:
        raise SecurityError("empty files are not accepted")
    if len(content) > max_bytes:
        raise SecurityError(f"file exceeds the {max_bytes}-byte limit")
    safe_filename = sanitize_filename(filename)
    detected = sniff_media_type(content)
    if detected not in ALLOWED_MEDIA_TYPES:
        raise SecurityError("file type is not allowlisted")
    if declared_media_type and declared_media_type.split(";", 1)[0].strip() != detected:
        raise SecurityError("declared media type does not match file content")
    return ValidatedUpload(
        filename=safe_filename,
        media_type=detected,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def detect_prompt_injection(text: str) -> list[str]:
    warnings: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if match := pattern.search(text):
            excerpt = re.sub(r"\s+", " ", match.group(0))[:100]
            warnings.append(f"untrusted instruction-like text detected: {excerpt}")
    return warnings


def redact_secrets(value: str) -> str:
    patterns = [
        re.compile(r"(?i)(api[_ -]?key|secret|token|password)\s*[:=]\s*[^\s,;]+"),
        re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]+"),
    ]
    result = value
    for pattern in patterns:
        result = pattern.sub("[REDACTED]", result)
    return result
