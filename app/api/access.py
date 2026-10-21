"""Who has been getting into the site, and from where.

Reads the record the access collector builds. Collection is triggered here as
well as on a timer, so opening the page is always looking at traffic up to the
last few seconds rather than whenever a scheduled job last ran.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.database import get_session
from app.config import settings
from app.services import auth, site_access
from app.services.auth import Principal

router = APIRouter(prefix="/api/access", tags=["access"])


def owner_only(principal: Principal) -> None:
    """One named account, not a role.

    Being an administrator is not enough and cannot be made enough from inside
    the application: this is not a Compliance module, so there is no tick box
    that turns it on for somebody, and adding one would not help because the
    check is on the address itself.
    """
    owner = (settings.access_log_owner or "").strip().lower()
    if not owner or (principal.email or "").strip().lower() != owner:
        raise HTTPException(status_code=403, detail={
            "error": "not_permitted",
            "message": "The site access record is restricted to its owner.",
        })


@router.get("")
async def list_access(
    days: int = Query(14, ge=1, le=180),
    include_robots: bool = Query(False),
    principal: Principal = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
):
    owner_only(principal)

    collected = await site_access.collect(session)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        audit = await auth.traccar_get(
            principal, f"/api/audit?from={since}&to="
                       f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", timeout=30)
        if audit:
            await site_access.name_accounts(session, audit)
    except Exception:                                  # noqa: BLE001 - the list still stands
        pass

    first_day = date.today() - timedelta(days=days - 1)
    query = select(site_access.SiteAccess).where(site_access.SiteAccess.day >= first_day)
    if not include_robots:
        query = query.where(site_access.SiteAccess.robot.is_(False))
    rows = (await session.execute(
        query.order_by(site_access.SiteAccess.last_seen.desc()).limit(2000))).scalars().all()

    # One line per address, rather than per address per day, is what reads
    # usefully: the same laptop on five days is one device, seen five days.
    merged: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.address, row.agent_hash)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = {
                "address": row.address, "device": row.device, "browser": row.browser,
                "agent": row.agent, "account": row.account, "robot": row.robot,
                "requests": 0, "app_requests": 0, "sign_ins": 0, "refused": 0,
                "days": 0, "used": set(),
                "first_seen": row.first_seen, "last_seen": row.last_seen,
            }
        entry["requests"] += row.requests
        entry["app_requests"] += row.app_requests
        entry["sign_ins"] += row.sign_ins
        entry["refused"] += row.refused
        entry["days"] += 1
        entry["account"] = entry["account"] or row.account
        if row.used:
            entry["used"].update(part.strip() for part in row.used.split(","))
        entry["first_seen"] = min(entry["first_seen"], row.first_seen)
        entry["last_seen"] = max(entry["last_seen"], row.last_seen)

    listing = sorted(merged.values(), key=lambda e: e["last_seen"], reverse=True)
    for entry in listing:
        entry["used"] = ", ".join(sorted(entry["used"]))
        entry["first_seen"] = entry["first_seen"].isoformat()
        entry["last_seen"] = entry["last_seen"].isoformat()

    robots = (await session.execute(
        select(func.count()).select_from(site_access.SiteAccess)
        .where(site_access.SiteAccess.day >= first_day)
        .where(site_access.SiteAccess.robot.is_(True)))).scalar() or 0

    return {
        "allowed": True,
        "days": days,
        "collected": collected,
        "summary": {
            "devices": len(listing),
            "addresses": len({e["address"] for e in listing}),
            "accounts": len({e["account"] for e in listing if e["account"]}),
            "sign_ins": sum(e["sign_ins"] for e in listing),
            "refused": sum(e["refused"] for e in listing),
            "robots": robots,
        },
        "rows": listing,
    }
