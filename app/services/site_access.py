"""Read the web server's access log into a record somebody can query.

The log is a text file the web server appends to for ever. This walks it from
wherever it was last read, folds the lines into one row per address, per
device, per day, and remembers the new position. Reading is incremental, so the
cost is the traffic since the last run rather than the whole file, and a log
that has been rotated (its size has gone backwards) is read again from the top.

Accounts come from DH FleetView's own sign-in audit, matched to the address
that signed in. That is the only way the two halves can be joined: the web
server sees addresses, and the application sees accounts.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.site_access import SiteAccess, SiteAccessCursor

logger = logging.getLogger("tacho.access")

LOG_PATHS = [p.strip() for p in (
    getattr(settings, "access_log_paths", None)
    or r"D:\CMSServer\apache2\logs\dhfleetview-access.log").split(",") if p.strip()]

LINE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) ([^" ]*)[^"]*" (\d{3}) (\S+) "([^"]*)" "([^"]*)"')
MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

# Requests only a signed-in person or one of the apps makes.
APP_PATHS = ("/api/session", "/api/devices", "/api/positions", "/api/reports", "/api/cmsv9",
             "/api/tachograph", "/api/commands", "/api/drivers", "/tacho/")
# Crawlers, scanners and uptime probes say so in their agent string.
ROBOTS = ("bot", "crawl", "spider", "scan", "palo alto", "censys", "expanse", "curl/",
          "python-requests", "go-http", "zgrab", "masscan", "headless", "wget", "okhttp/3",
          "playstore-google", "googleother", "cms-checker", "checker", "monitor", "uptime",
          "facebookexternalhit", "slackbot", "whatsapp", "preview", "fetcher", "libwww",
          "java/", "axios", "node-fetch", "postman")

# How much of the log to swallow in one pass, so a first run on a 60 MB file
# does not hold the server up.
MAX_BYTES_PER_PASS = 12 * 1024 * 1024


def device_of(agent: str) -> str:
    a = agent.lower()
    if "okhttp" in a or "dart" in a or "dhfleetview" in a:
        return "DH FleetView app"
    for needle, name in (("android", "Android"), ("iphone", "iPhone"), ("ipad", "iPad"),
                         ("macintosh", "Mac"), ("mac os", "Mac"), ("windows nt", "Windows PC"),
                         ("cros", "Chromebook"), ("linux", "Linux")):
        if needle in a:
            return name
    return "unknown"


def browser_of(agent: str) -> str:
    a = agent.lower()
    for needle, name in (("edg/", "Edge"), ("opr/", "Opera"), ("chrome/", "Chrome"),
                         ("firefox/", "Firefox"), ("safari/", "Safari"),
                         ("okhttp", "app"), ("dart", "app")):
        if needle in a:
            return name
    return "other"


def _moment(stamp: str) -> datetime | None:
    """Apache writes its own local time with the offset; keep it absolute."""
    try:
        day, month, rest = stamp[:2], stamp[3:6], stamp[7:]
        year, clock, zone = rest[:4], rest[5:13], rest[14:].strip()
        sign = 1 if zone.startswith("+") else -1
        delta = timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5]))
        naive = datetime(int(year), MONTHS[month], int(day),
                         int(clock[:2]), int(clock[3:5]), int(clock[6:8]))
        return (naive - sign * delta).replace(tzinfo=timezone.utc)
    except (ValueError, KeyError, IndexError):
        return None


@dataclass
class Visit:
    """One address on one device for one day, as it is being counted up."""

    agent: str
    device: str
    browser: str
    first_seen: datetime
    last_seen: datetime
    requests: int = 0
    app_requests: int = 0
    sign_ins: int = 0
    refused: int = 0
    areas: set[str] = field(default_factory=set)
    robot: bool = False


def _area(path: str) -> str | None:
    if path.startswith("/tacho/"):
        return "compliance"
    if path.startswith("/api/cmsv9"):
        return "video"
    if path.startswith("/api/reports"):
        return "reports"
    if path.startswith(APP_PATHS):
        return "fleet"
    return None


async def collect(session: AsyncSession) -> dict:
    """Read whatever is new in the logs and fold it into the record."""
    total_lines = 0
    visits: dict[tuple, Visit] = {}

    for path in LOG_PATHS:
        if not os.path.isfile(path):
            logger.info("access log not found: %s", path)
            continue
        size = os.path.getsize(path)
        cursor = await session.get(SiteAccessCursor, path)
        start = cursor.offset if cursor else 0
        if cursor and size < cursor.size:
            logger.info("%s has been rotated; reading from the start", path)
            start = 0
        if start >= size:
            continue
        end = min(size, start + MAX_BYTES_PER_PASS)

        with io.open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
            handle.seek(start)
            chunk = handle.read(end - start)
        # Never leave half a line behind.
        cut = chunk.rfind("\n")
        if cut == -1:
            continue
        consumed = len(chunk[:cut + 1].encode("utf-8", "replace"))
        for line in chunk[:cut].splitlines():
            match = LINE.match(line)
            if not match:
                continue
            address, stamp, _method, request_path, status, _size, _ref, agent = match.groups()
            when = _moment(stamp)
            if when is None:
                continue
            total_lines += 1
            agent = agent[:400]
            key = (when.date(), address, hashlib.md5(agent.encode()).hexdigest()[:32])
            visit = visits.get(key)
            if visit is None:
                visit = visits[key] = Visit(
                    agent=agent, device=device_of(agent), browser=browser_of(agent),
                    first_seen=when, last_seen=when,
                    robot=any(r in agent.lower() for r in ROBOTS))
            visit.requests += 1
            visit.first_seen = min(visit.first_seen, when)
            visit.last_seen = max(visit.last_seen, when)
            area = _area(request_path)
            if area:
                visit.app_requests += 1
                visit.areas.add(area)
            if request_path.startswith("/api/session") and status == "200":
                visit.sign_ins += 1
            if status in ("401", "403"):
                visit.refused += 1

        await session.execute(insert(SiteAccessCursor).values(
            path=path, offset=start + consumed, size=size,
            read_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=[SiteAccessCursor.path],
            set_={"offset": start + consumed, "size": size, "read_at": datetime.now(timezone.utc)},
        ))

    for (day, address, agent_hash), visit in visits.items():
        await session.execute(insert(SiteAccess).values(
            day=day, address=address, agent=visit.agent, agent_hash=agent_hash,
            device=visit.device, browser=visit.browser,
            first_seen=visit.first_seen, last_seen=visit.last_seen,
            requests=visit.requests, app_requests=visit.app_requests,
            sign_ins=visit.sign_ins, refused=visit.refused,
            used=", ".join(sorted(visit.areas))[:120] or None,
            robot=visit.robot,
        ).on_conflict_do_update(
            constraint="uq_site_access_day_address_agent",
            set_={
                # A day already counted is added to, never replaced.
                "requests": SiteAccess.requests + visit.requests,
                "app_requests": SiteAccess.app_requests + visit.app_requests,
                "sign_ins": SiteAccess.sign_ins + visit.sign_ins,
                "refused": SiteAccess.refused + visit.refused,
                "last_seen": visit.last_seen,
                "used": ", ".join(sorted(visit.areas))[:120] or None,
            },
        ))
    await session.commit()
    return {"lines": total_lines, "rows": len(visits)}


async def name_accounts(session: AsyncSession, audit: list[dict]) -> int:
    """Put an account against the addresses that signed in.

    The audit comes from DH FleetView and carries the address each sign-in came
    from. Where several accounts share an address - an office on one line - the
    most recent one is recorded, and the rest remain visible in the audit.
    """
    by_address: dict[str, set[str]] = {}
    for row in audit:
        if row.get("actionType") != "login" or not row.get("address"):
            continue
        who = row.get("userEmail") or f"user {row.get('userId')}"
        by_address.setdefault(row["address"], set()).add(who)

    named = 0
    for address, accounts in by_address.items():
        # Several accounts from one address is normal in an office; naming them
        # all is honest, naming the latest one is not.
        who = ", ".join(sorted(accounts))[:200]
        rows = (await session.execute(
            select(SiteAccess).where(SiteAccess.address == address))).scalars().all()
        for row in rows:
            if row.account != who:
                row.account = who
                named += 1
    await session.commit()
    return named


async def watch(every_seconds: int = 300) -> None:
    """Keep the record up to date while the server runs.

    The page triggers a read of its own, but a record that only exists when
    somebody looks at it is not a record. This keeps it current, and survives a
    log that disappears or a database that is briefly unavailable.
    """
    from app.database import SessionLocal

    while True:
        try:
            async with SessionLocal() as session:
                outcome = await collect(session)
            if outcome["lines"]:
                logger.info("site access: %d new lines, %d device-days",
                            outcome["lines"], outcome["rows"])
        except asyncio.CancelledError:
            raise
        except Exception:                               # noqa: BLE001 - never stop watching
            logger.exception("could not read the access log")
        await asyncio.sleep(every_seconds)
