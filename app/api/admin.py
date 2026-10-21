"""Super administrator: platform health (nightly backups).

GET /api/admin/backup-status   result of the last nightly backup (scripts/backup.ps1)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_manager
from app.config import settings
from app.services import modules
from app.services.auth import Principal

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/backup-status")
async def backup_status(principal: Principal = Depends(require_manager)) -> dict:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only the super administrator can see backups.")
    path = Path(settings.backup_status_file)
    if not path.exists():
        return {"configured": False, "healthy": False, "message": "No backup has run yet."}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"configured": True, "healthy": False, "message": "The backup status file couldn't be read."}
    last_success = data.get("last_success")
    age_hours = None
    if last_success:
        age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last_success)).total_seconds() / 3600
    healthy = data.get("last_result") == "ok" and age_hours is not None and age_hours <= 36
    return {"configured": True, "healthy": healthy, "last_success": last_success,
            "hours_since_success": None if age_hours is None else round(age_hours, 1),
            "last_result": data.get("last_result"), "size_mb": data.get("last_size_mb"), "checks": data.get("checks")}
