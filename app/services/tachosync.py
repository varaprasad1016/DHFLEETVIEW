"""TachoSync (Teltonika) REST API client.

TachoSync runs the half of the WEB Tacho protocol we cannot: it drives the unit
after it connects, relays the company card's authentication into the tachograph,
and receives the DDD file. This module brings the finished files back here, so
the archive, the compliance checks and the reports stay on our side and
TachoSync does only the part that is theirs.

Authentication is a company-scoped API key in an X-API-KEY header. The key is
read from the environment and never logged - including in error messages, which
is why failures quote the status and the endpoint rather than the request.

API: https://api.tacho.teltonika.lt/swagger/v1/swagger.json
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from app.config import settings

logger = logging.getLogger("tacho.tachosync")

BASE_URL = "https://api.tacho.teltonika.lt/v1"
TIMEOUT = httpx.Timeout(30.0, read=120.0)   # a file download is the slow one
PAGE_SIZE = 100                             # the API's maximum


class TachoSyncError(RuntimeError):
    """A request was refused or the service is unreachable."""


def configured() -> bool:
    return bool((settings.tachosync_api_key or "").strip())


def _headers(key: str | None = None) -> dict[str, str]:
    """The key for this request: the customer's own, or the server-wide one.

    A customer's downloads live in their own TachoSync company, so which key is
    used decides which fleet's files come back. Getting that wrong would put one
    operator's tachograph data into another's archive, so the key is carried
    explicitly through every call rather than read from a global.
    """
    key = (key or settings.tachosync_api_key or "").strip()
    if not key:
        raise TachoSyncError("No TachoSync API key is configured for this customer.")
    return {"X-API-KEY": key, "Accept": "application/json"}


async def _get(path: str, params: dict | None = None, key: str | None = None) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(f"{BASE_URL}/{path}", params=params, headers=_headers(key))
        except httpx.HTTPError as exc:
            raise TachoSyncError(f"TachoSync is unreachable ({exc.__class__.__name__}).") from exc
    if response.status_code == 401:
        raise TachoSyncError("TachoSync rejected the API key: it may be disabled, expired or deleted.")
    if response.status_code >= 400:
        raise TachoSyncError(f"TachoSync answered {response.status_code} for {path}.")
    return response.json()


async def _paged(path: str, params: dict | None = None, limit: int = 1000,
                 key: str | None = None) -> list[dict]:
    """Every page of a paged endpoint, up to a sane ceiling."""
    items: list[dict] = []
    page = 1
    while len(items) < limit:
        body = await _get(path, {**(params or {}), "PageNumber": page, "PageSize": PAGE_SIZE}, key)
        items.extend(body.get("items") or [])
        if not body.get("hasNext"):
            break
        page += 1
    return items[:limit]


# --- what the account holds -------------------------------------------------------------------

async def company(key: str | None = None) -> dict:
    return await _get("Companies", key=key)


async def vehicles(key: str | None = None) -> list[dict]:
    return await _paged("Vehicles", key=key)


async def drivers(key: str | None = None) -> list[dict]:
    return await _paged("Drivers", key=key)


async def driver_detail(driver_id: str, key: str | None = None) -> dict:
    """One driver card, with the state of each schedule against it.

    The listing says whether a card has ever been downloaded; only this says
    what the schedule is waiting for. A card is not downloaded on a timer like
    a vehicle unit - it can only be read while the card is in a tachograph and
    that unit is connected - so "waiting for device connection" is the normal
    resting state, not a fault, and the difference matters when somebody is
    asking why no file has arrived.
    """
    return await _get(f"Drivers/{driver_id}", key=key) or {}


async def download_driver_now(driver_id: str, company_id: str,
                              key: str | None = None) -> dict:
    """Ask TachoSync for this card as soon as it can have it.

    A one-time schedule on top of whatever else is set. It does not reach the
    card by itself - nothing can - it means the next time that card is in a
    tachograph and the unit is connected, this download happens rather than
    waiting for the daily schedule's turn. Worth doing when somebody can see
    the driver is in the lorry now.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/DriverSchedules/Quick", headers=_headers(key),
                json={"driverId": driver_id, "companyId": company_id})
        except httpx.HTTPError as exc:
            raise TachoSyncError(f"TachoSync is unreachable ({exc.__class__.__name__}).") from exc
    if response.status_code == 401:
        raise TachoSyncError("TachoSync rejected the API key.")
    if response.status_code >= 400:
        raise TachoSyncError(
            f"TachoSync answered {response.status_code} asking for that card.")
    return response.json() or {}


async def downloads_history(vehicle_id: str) -> list[dict]:
    """Recent download attempts for one vehicle, successes and failures alike.

    This is the only place that says *why* a download did not happen - the
    stage it reached and the reason it stopped - so it is worth surfacing
    rather than keeping for debugging.
    """
    return await _get(f"Vehicles/{vehicle_id}/DownloadsHistory") or []


async def vehicle_files(since: datetime | None = None, key: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"Descending": True}
    if since:
        params["From"] = since.astimezone(timezone.utc).isoformat()
    return await _paged("VehicleFiles", params, key=key)


async def driver_files(since: datetime | None = None, key: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"Descending": True}
    if since:
        params["From"] = since.astimezone(timezone.utc).isoformat()
    return await _paged("DriverFiles", params, key=key)


async def download(kind: str, ids: Iterable[str], key: str | None = None) -> tuple[bytes, str]:
    """The file content for one or more ids.

    One id returns the file itself; several return a zip of them, which is the
    API's own behaviour and why the content type comes back with the bytes.
    """
    path = "VehicleFiles/Download" if kind == "vehicle" else "DriverFiles/Download"
    params = [("Ids", str(i)) for i in ids]
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(f"{BASE_URL}/{path}", params=params, headers=_headers(key))
        except httpx.HTTPError as exc:
            raise TachoSyncError(f"TachoSync is unreachable ({exc.__class__.__name__}).") from exc
    if response.status_code >= 400:
        raise TachoSyncError(f"TachoSync answered {response.status_code} downloading {kind} files.")
    return response.content, response.headers.get("content-type", "application/octet-stream")


# --- bringing files home ----------------------------------------------------------------------

def _file_name(entry: dict, kind: str) -> str:
    """TachoSync's own name where it gives one, otherwise something recognisable."""
    for key in ("fileName", "name", "originalFileName"):
        if entry.get(key):
            return str(entry[key])
    stamp = str(entry.get("createdAt") or "")[:19].replace(":", "").replace("-", "")
    who = entry.get("vehicleNumber") or entry.get("driverName") or entry.get("imei") or kind
    return f"{who}-{stamp}.ddd"


async def sync_company(key: str, company_id, days: int = 30) -> dict:
    """Pull one customer's files, using that customer's own key."""
    from app.services import download_ingest

    since = datetime.now(timezone.utc) - timedelta(days=days)
    fetched, skipped, errors = 0, 0, []
    for kind, lister in (("vehicle", vehicle_files), ("driver", driver_files)):
        try:
            entries = await lister(since, key=key)
        except TachoSyncError as exc:
            errors.append(str(exc))
            continue
        for entry in entries:
            name = _file_name(entry, kind)
            file_id = entry.get("id")
            if not file_id:
                continue
            try:
                content, _ = await download(kind, [file_id], key=key)
                # The ingest keeps one copy per sha256 and says when it already
                # had the file, so re-running costs a fetch and nothing else.
                outcome = await download_ingest.ingest(
                    content, name,
                    imei=entry.get("imei") or entry.get("vehicleImei"),
                    vehicle_ref=entry.get("vehicleNumber"),
                    source="tachosync", company_id=company_id)
                if outcome.get("duplicate"):
                    skipped += 1
                    continue
                fetched += 1
                logger.info("brought %s home from TachoSync (%d bytes)", name, len(content))
            except TachoSyncError as exc:
                errors.append(f"{name}: {exc}")
            except Exception as exc:                    # noqa: BLE001 - one bad file is not the run
                errors.append(f"{name}: {exc}")
    return {"fetched": fetched, "skipped": skipped, "errors": errors}


async def sync(days: int = 30) -> dict:
    """Pull anything new for every customer that has a key.

    Each customer's files are fetched with that customer's own key and filed
    against that customer, which is what keeps one operator's downloads out of
    another's archive. A deployment with a single server-wide key and no
    per-customer keys still works exactly as it did.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.core import Company

    totals = {"configured": True, "fetched": 0, "skipped": 0, "errors": [], "companies": 0}

    async with SessionLocal() as session:
        companies = (await session.execute(
            select(Company).where(Company.tachosync_api_key.isnot(None)))).scalars().all()
        keyed = [(c.id, c.name, (c.tachosync_api_key or "").strip()) for c in companies
                 if (c.tachosync_api_key or "").strip()]

    if not keyed:
        # No customer keys yet: fall back to the server-wide key, if there is one.
        if not configured():
            return {"configured": False, "fetched": 0, "skipped": 0, "errors": [], "companies": 0}
        outcome = await sync_company(settings.tachosync_api_key, None, days)
        return {**totals, **outcome, "companies": 1}

    for company_id, name, key in keyed:
        outcome = await sync_company(key, company_id, days)
        totals["fetched"] += outcome["fetched"]
        totals["skipped"] += outcome["skipped"]
        totals["errors"] += [f"{name}: {e}" for e in outcome["errors"]]
        totals["companies"] += 1
        await _note_status(company_id, outcome)
    return totals


async def _note_status(company_id, outcome: dict) -> None:
    """Record how that customer's last fetch went, for the setup screen."""
    from app.database import SessionLocal
    from app.models.core import Company

    async with SessionLocal() as session:
        company = await session.get(Company, company_id)
        if company is None:
            return
        company.tachosync_checked_at = datetime.now(timezone.utc)
        company.tachosync_status = (
            outcome["errors"][0][:200] if outcome["errors"]
            else f"{outcome['fetched']} new, {outcome['skipped']} already held")
        await session.commit()



async def watch(every_seconds: int = 1800, days: int = 30) -> None:
    """Keep the archive in step with TachoSync without anyone pressing a button.

    A tachograph download is only useful once it is in the archive, analysed
    and attached to its vehicle, and nobody should have to remember to fetch
    it. This runs the same sync the page's button runs, on a timer.

    Nothing here needs to guard against doing the work twice: the ingest keeps
    one copy per sha256, so a file already held costs a fetch and is then
    dropped, and the analysis only ever runs on a file the first time it
    arrives.
    """
    import asyncio

    if not configured():
        logger.info("TachoSync is not configured; the automatic fetch is off")
        return

    while True:
        try:
            outcome = await sync(days=days)
            if outcome.get("fetched") or outcome.get("errors"):
                logger.info("TachoSync: %d new, %d already held, %d problems",
                            outcome.get("fetched", 0), outcome.get("skipped", 0),
                            len(outcome.get("errors") or []))
        except asyncio.CancelledError:
            raise
        except Exception:                                   # noqa: BLE001 - never stop fetching
            logger.exception("the TachoSync fetch failed; will try again")
        await asyncio.sleep(every_seconds)
