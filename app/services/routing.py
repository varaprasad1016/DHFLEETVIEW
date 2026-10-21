"""Getting a driver to the job, and telling them what is in the way.

Three jobs, deliberately separate:

* turn the job's written addresses into coordinates (Nominatim),
* work out the road route between them (OSRM),
* say which live closures that route passes (DH FleetView's own feed).

The navigation itself is handed to the phone's maps app, which knows about
traffic we never will. What this adds is the thing a maps app will not tell the
office: that tomorrow's run goes through a closure National Highways already
has on the books.

Both outside services are free and rate-limited by courtesy rather than keys,
so addresses are cached and nothing is called in a loop. For real volume the
right answer is an OSRM instance of our own - it is one container - and this
module is where that change would happen.
"""

from __future__ import annotations

import logging
import math
import re
import time
from urllib.parse import quote_plus

import httpx

from app.config import settings

logger = logging.getLogger("tacho.routing")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "DHFleetView/1.0 (fleet compliance platform)"
TIMEOUT = httpx.Timeout(20.0)

# How close a closure has to be to the line of the route to count as on it.
# The route is a string of points a few tens of metres apart, so this is really
# "within a few hundred metres of the road we would drive".
ON_ROUTE_METRES = 400

# Nominatim asks for no more than one request a second, and the same depot
# address is looked up for every job that goes there.
_geocode_cache: dict[str, tuple[float, float] | None] = {}
_last_geocode = 0.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def geocode(address: str) -> tuple[float, float] | None:
    """Coordinates for a written address, or None if it cannot be placed.

    A postcode on its own is usually enough and is what most job sheets carry;
    a free-text yard name often is not, and a miss here is not an error - the
    navigation link still works, because the maps app does its own search.
    """
    global _last_geocode
    if not address or not address.strip():
        return None
    key = address.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]

    wait = 1.1 - (time.monotonic() - _last_geocode)
    if wait > 0:
        time.sleep(wait)
    _last_geocode = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(NOMINATIM, params={
                "q": address, "format": "json", "limit": 1, "countrycodes": "gb"})
        rows = response.json() if response.status_code == 200 else []
    except Exception as exc:                      # noqa: BLE001 - a miss is survivable
        logger.info("could not geocode %r: %s", address[:60], exc)
        rows = []

    found = (float(rows[0]["lat"]), float(rows[0]["lon"])) if rows else None
    _geocode_cache[key] = found
    return found


async def route(origin: tuple[float, float], destination: tuple[float, float]) -> dict | None:
    """The driving route between two points: distance, time and its shape."""
    url = (f"{OSRM}/{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
           "?overview=full&geometries=geojson")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(url)
        body = response.json()
    except Exception as exc:                      # noqa: BLE001
        logger.info("routing failed: %s", exc)
        return None
    routes = body.get("routes") or []
    if not routes:
        return None
    best = routes[0]
    points = [(c[1], c[0]) for c in best["geometry"]["coordinates"]]
    return {
        "distance_km": round(best["distance"] / 1000, 1),
        "duration_min": round(best["duration"] / 60),
        "points": points,
    }


async def live_closures() -> list[dict]:
    """Live disruption from our own feed, via DH FleetView."""
    token = (settings.traccar_api_token or "").strip()
    if not token:
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                "http://127.0.0.1:8090/api/disruptions",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if response.status_code != 200:
            return []
        return response.json().get("items") or []
    except Exception as exc:                      # noqa: BLE001
        logger.info("could not read the disruption feed: %s", exc)
        return []


def closures_on(points: list[tuple[float, float]], closures: list[dict]) -> list[dict]:
    """Which closures the route actually passes.

    Checked against the route's own points rather than a straight line between
    the ends: a job from Kent to Carlisle passes nowhere near the straight line
    it would be drawn on.
    """
    out = []
    for closure in closures:
        lat, lon = closure.get("latitude"), closure.get("longitude")
        if not lat and not lon:
            continue
        nearest = min((_haversine_m(lat, lon, p[0], p[1]) for p in points), default=None)
        if nearest is not None and nearest <= ON_ROUTE_METRES:
            out.append({**closure, "metres_from_route": round(nearest)})
    out.sort(key=lambda c: c["metres_from_route"])
    return out


def nav_url(pickup: str | None, dropoff: str | None) -> str | None:
    """A link that opens the phone's own maps app, navigating to the job.

    Google's universal directions URL, which Android opens in Google Maps and
    iOS opens in Google Maps if installed and Safari's maps otherwise. Written
    addresses are passed through as typed: the maps app's own search handles a
    yard name or a postcode better than we can, and it is what the driver would
    have typed anyway.
    """
    if not dropoff or not dropoff.strip():
        return None
    url = ("https://www.google.com/maps/dir/?api=1"
           f"&destination={quote_plus(dropoff.strip())}&travelmode=driving")
    if pickup and pickup.strip():
        url += f"&origin={quote_plus(pickup.strip())}"
    return url


def apple_url(pickup: str | None, dropoff: str | None) -> str | None:
    """The same for an iPhone with no Google Maps installed."""
    if not dropoff or not dropoff.strip():
        return None
    url = f"https://maps.apple.com/?daddr={quote_plus(dropoff.strip())}&dirflg=d"
    if pickup and pickup.strip():
        url += f"&saddr={quote_plus(pickup.strip())}"
    return url


async def plan(pickup: str | None, dropoff: str | None) -> dict:
    """Everything the driver app needs for one job.

    Degrades in steps rather than failing: without a route there is still a
    navigation link, and without coordinates there is still the address the
    office typed.
    """
    result: dict = {
        "navigation": nav_url(pickup, dropoff),
        "navigation_apple": apple_url(pickup, dropoff),
        "pickup": pickup,
        "dropoff": dropoff,
        "distance_km": None,
        "duration_min": None,
        "closures": [],
        "checked": False,
    }
    origin = await geocode(pickup) if pickup else None
    destination = await geocode(dropoff) if dropoff else None
    if not origin or not destination:
        return result

    leg = await route(origin, destination)
    if not leg:
        return result
    result["distance_km"] = leg["distance_km"]
    result["duration_min"] = leg["duration_min"]
    result["closures"] = closures_on(leg["points"], await live_closures())
    result["checked"] = True
    return result


def summarise(plan_result: dict) -> str | None:
    """One line an office can read, or send to a driver as a message."""
    closures = plan_result.get("closures") or []
    if not plan_result.get("checked"):
        return None
    if not closures:
        return "Route checked: no closures on it."
    roads = []
    for closure in closures:
        road = closure.get("road") or re.sub(r"\s+", " ", (closure.get("where") or ""))[:20]
        if road and road not in roads:
            roads.append(road)
    return f"{len(closures)} closure{'s' if len(closures) != 1 else ''} on this route: {', '.join(roads[:4])}"
