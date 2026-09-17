"""Local filesystem store for walkaround photos and driver signatures.

Images arrive as data URLs (base64) from the driver form and are written under
data/walkaround/, addressed by a random id. Kept off the database to avoid
bloating it. Served back through the licence-gated API.
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from app.config import settings

_DATA_URL = re.compile(r"^data:(?P<ct>[\w/+.\-]+);base64,(?P<data>.*)$", re.DOTALL)
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp"}
_MAX_BYTES = 8 * 1024 * 1024  # 8 MB per image


def _root() -> Path:
    p = Path(settings.archive_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p
    root = p.parent / "walkaround"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_data_url(data_url: str) -> dict:
    """Persist a base64 data URL image; return {storage_path, content_type}."""
    m = _DATA_URL.match(data_url.strip())
    if m:
        content_type = m.group("ct").lower()
        raw = base64.b64decode(m.group("data"), validate=False)
    else:
        content_type = "image/jpeg"
        raw = base64.b64decode(data_url, validate=False)
    if not raw:
        raise ValueError("empty image")
    if len(raw) > _MAX_BYTES:
        raise ValueError("image too large")
    ext = _EXT.get(content_type, "bin")
    path = _root() / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(raw)
    return {"storage_path": str(path), "content_type": content_type}


def read(storage_path: str) -> bytes:
    return Path(storage_path).read_bytes()


_DOC_EXT = {**_EXT, "application/pdf": "pdf"}
_DOC_MAX_BYTES = 15 * 1024 * 1024


def save_document(data_url: str) -> dict:
    """Persist an uploaded document (PDF or photo) sent as a base64 data URL."""
    m = _DATA_URL.match((data_url or "").strip())
    if not m:
        raise ValueError("not a data URL")
    content_type = m.group("ct").lower()
    if content_type not in _DOC_EXT:
        raise ValueError("only PDF, JPEG, PNG or WebP files")
    raw = base64.b64decode(m.group("data"), validate=False)
    if not raw:
        raise ValueError("empty file")
    if len(raw) > _DOC_MAX_BYTES:
        raise ValueError("file too large (15 MB max)")
    path = _root() / f"{uuid.uuid4().hex}.{_DOC_EXT[content_type]}"
    path.write_bytes(raw)
    return {"storage_path": str(path), "content_type": content_type, "size_bytes": len(raw)}
