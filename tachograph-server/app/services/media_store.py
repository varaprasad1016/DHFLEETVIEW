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
