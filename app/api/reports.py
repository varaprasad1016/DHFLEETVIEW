"""PDF reports built from the fleet's own position history.

The figures come from DH FleetView's report engine, which is the same thing the
on-screen tables are built from, so a PDF can never disagree with the screen.
What is added here is the part a yard actually needs: totals, a readable page,
and a plain statement of which GPS the positions came from.

Which GPS: a vehicle with a tracker fitted is reported from the tracker, and one
without is reported from its camera. That preference is applied when positions
are stored, so the history already holds the better of the two; this reads back
what was used and says so on the page.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import require_manager
from app.config import settings
from app.services import auth, places, report_pdf
from app.services.auth import Principal

router = APIRouter(prefix="/api/reports", tags=["reports"])

UK = ZoneInfo("Europe/London")

KINDS = {
    "trips": "Trips report",
    "stops": "Stops report",
    "summary": "Summary report",
    "events": "Events report",
}


async def _source_of(principal: Principal, devices: list[dict]) -> tuple[str, str]:
    """Which GPS these positions came from, and the detail line under it."""
    tracked, camera = [], []
    for device in devices:
        attributes = device.get("attributes") or {}
        if attributes.get("trackerImei") or attributes.get("trackerModel"):
            tracked.append(device)
        elif attributes.get("cmsv9DeviceId"):
            camera.append(device)

    if tracked and not camera:
        models = {(d.get("attributes") or {}).get("trackerModel") for d in tracked}
        models.discard(None)
        detail = ", ".join(sorted(models)) if models else ""
        return "Vehicle tracker", detail
    if camera and not tracked:
        return "Vehicle camera (DVR)", "No separate tracker fitted; positions are the camera's own GPS"
    if tracked and camera:
        return "Mixed", (f"{len(tracked)} from a tracker, {len(camera)} from the vehicle camera")
    return "Unknown", ""


# A coordinate is not an answer to "where was it". Resolving them is the places
# service's job - it keeps what it learns, and knows how slowly it is allowed to
# ask - so this only has to say which fields hold a place.
_PLACES = {
    "trips": [("startAddress", "startLat", "startLon"), ("endAddress", "endLat", "endLon")],
    "stops": [("address", "latitude", "longitude")],
    "events": [("address", "latitude", "longitude")],
    "summary": [],
}


async def _fill_addresses(kind: str, rows: list[dict]) -> None:
    """Put a street name where a row has only numbers."""
    fields = _PLACES.get(kind) or []
    if not fields:
        return

    wanted: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for row in rows:
        for address, lat_key, lon_key in fields:
            if row.get(address):
                continue
            lat, lon = row.get(lat_key), row.get(lon_key)
            if lat is None or lon is None:
                continue
            point = (lat, lon)
            if point not in seen:
                seen.add(point)
                wanted.append(point)

    if not wanted:
        return
    known = await places.fill(wanted)

    for row in rows:
        for address, lat_key, lon_key in fields:
            if row.get(address):
                continue
            lat, lon = row.get(lat_key), row.get(lon_key)
            if lat is None or lon is None:
                continue
            found = known.get(f"{round(lat, 4)},{round(lon, 4)}")
            if found:
                row[address] = found


@router.get("/pdf", dependencies=[])
async def report_pdf_download(
    kind: str = Query(..., description="trips, stops, summary or events"),
    deviceId: list[int] = Query(default=[]),
    frm: str = Query(..., alias="from"),
    to: str = Query(...),
    principal: Principal = Depends(require_manager),
):
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"{kind} is not a report this can produce.")
    if not deviceId:
        raise HTTPException(status_code=400, detail="Choose at least one vehicle.")

    query = [("from", frm), ("to", to)] + [("deviceId", str(d)) for d in deviceId]
    path = f"/api/reports/{kind}?{urllib.parse.urlencode(query)}"
    # A month of positions takes DH FleetView a while to work through, and the
    # default five seconds is for small lookups; a report that covers a quarter
    # is a legitimate thing to ask for and must not time out halfway.
    rows = await auth.traccar_get(principal, path, timeout=180)
    if rows is None:
        raise HTTPException(status_code=502, detail="DH FleetView did not return the report.")

    everything = await auth.traccar_get(principal, "/api/devices") or []
    wanted = {d["id"]: d for d in everything if d["id"] in set(deviceId)}
    devices = [wanted[i] for i in deviceId if i in wanted]
    if not devices:
        raise HTTPException(status_code=404, detail="That vehicle is not on your account.")

    await _fill_addresses(kind, rows)
    source, detail = await _source_of(principal, devices)

    def moment(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UK)

    report = report_pdf.Report(
        kind=kind,
        title=KINDS[kind],
        brand=getattr(settings, "white_label_title", None) or "DH FleetView",
        period_from=moment(frm),
        period_to=moment(to),
        vehicles=devices,
        rows=rows,
        source=source,
        source_detail=detail,
        figures=report_pdf.figures_for(kind, rows),
        note="Times are UK local time",
    )
    pdf = report_pdf.render(report)

    plate = (devices[0].get("name") or "fleet").replace(" ", "")
    stamp = report.period_from.strftime("%Y%m%d")
    filename = f"{plate}-{kind}-{stamp}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    })


@router.post("/places")
async def resolve_places(
    points: list[dict],
    principal: Principal = Depends(require_manager),
):
    """Street names for a list of {latitude, longitude}, for the report table.

    Answers in the order it was asked, one entry per point, so the caller
    matches by position. Matching on a stringified coordinate looked simpler
    and was wrong: Python writes 51.5 where JavaScript writes 51.5000, and
    every place at a round coordinate quietly failed to line up.
    """
    wanted = []
    for point in points[:400]:
        try:
            wanted.append((float(point["latitude"]), float(point["longitude"])))
        except (KeyError, TypeError, ValueError):
            wanted.append(None)

    known = await places.fill([p for p in wanted if p is not None])
    return [None if point is None
            else known.get(f"{round(point[0], 4)},{round(point[1], 4)}")
            for point in wanted]
