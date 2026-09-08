"""Local filesystem archive for tacho download files.

The native deploy has no MinIO, so downloaded .ddd/.tgd/.v1b/.c1b files are kept
on disk under settings.archive_path, addressed by SHA-256 and organised by
year/month. DVSA requires driver-card and vehicle-unit data to be retained for
at least 12 months; we stamp a retain_until and never auto-purge before it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings


def _root() -> Path:
    root = Path(settings.archive_path)
    if not root.is_absolute():
        # relative to the project root (two levels up from this file: app/services/)
        root = Path(__file__).resolve().parents[2] / root
    return root


def retain_until(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=30 * settings.archive_retention_months)


def store(filename: str, data: bytes, now: datetime | None = None) -> dict:
    """Persist bytes; return archive metadata (idempotent by content hash)."""
    now = now or datetime.now(timezone.utc)
    sha = hashlib.sha256(data).hexdigest()
    ext = Path(filename).suffix.lower() or ".bin"
    folder = _root() / f"{now:%Y}" / f"{now:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}{ext}"
    if not path.exists():
        path.write_bytes(data)
    return {
        "storage_path": str(path),
        "sha256": sha,
        "size_bytes": len(data),
        "retain_until": retain_until(now),
    }


def read(storage_path: str) -> bytes:
    return Path(storage_path).read_bytes()
