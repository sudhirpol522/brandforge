from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from .exceptions import NotFoundError, SecurityError


def validate_object_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise SecurityError("invalid object key")
    return str(path)


class LocalObjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, content: bytes, media_type: str) -> str:
        del media_type
        safe_key = validate_object_key(key)
        target = (self.root / safe_key).resolve()
        if self.root not in target.parents:
            raise SecurityError("object key escapes the configured store")
        target.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return safe_key

    def get(self, key: str) -> bytes:
        safe_key = validate_object_key(key)
        target = (self.root / safe_key).resolve()
        if self.root not in target.parents:
            raise SecurityError("object key escapes the configured store")
        if not target.is_file():
            raise NotFoundError(f"object {safe_key} not found")
        return target.read_bytes()
