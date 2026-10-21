"""Turning coordinates into places, once.

DH FleetView's own reverse geocoder is pointed at LocationIQ's keyless endpoint
and answers 429 to nearly everything, which is why reports and position records
have been full of latitudes instead of street names. Until a provider key is
configured, this asks OpenStreetMap's Nominatim instead - the same service the
job routing already uses - inside its one-request-a-second courtesy limit.

Every place learned is written to disk, so the second report covering the same
yard, depot or quarry costs nothing and is instant. A fleet goes to the same
places week after week, so the cache fills quickly and stays useful.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("tacho.places")

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "DHFleetView/1.0 (fleet compliance platform)"
TIMEOUT = httpx.Timeout(20.0)

# Nominatim asks for no more than one request a second.
PAUSE = 1.1
# ~11 metres: the same gateway twice is one place, not two.
PRECISION = 4

CACHE_FILE = Path(getattr(settings, "places_cache_path", None)
                  or r"D:\DHFleetViewData\places-cache.json")
CACHE_MAX = 50000

_places: dict[str, str] = {}
_loaded = False
_last_call = 0.0
_lock = asyncio.Lock()


def _key(latitude: float, longitude: float) -> str:
    return f"{round(latitude, PRECISION)},{round(longitude, PRECISION)}"


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        _places.update(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
        logger.info("%d places remembered from previous reports", len(_places))
    except (OSError, ValueError):
        pass


def _save() -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_places), encoding="utf-8")
    except OSError as exc:                              # noqa: BLE001
        logger.info("could not save the places cache: %s", exc)


def known(latitude: float, longitude: float) -> str | None:
    """A place already learned, without asking anyone."""
    _load()
    return _places.get(_key(latitude, longitude))


def _tidy(address: dict) -> str:
    """The parts of an address a driver would say, in that order."""
    road = address.get("road") or address.get("pedestrian") or address.get("industrial")
    spot = (address.get("village") or address.get("town") or address.get("suburb")
            or address.get("city") or address.get("hamlet") or address.get("county"))
    name = address.get("amenity") or address.get("shop") or address.get("building")
    parts = [p for p in (name, road, spot) if p]
    # Nominatim repeats itself often enough to be worth guarding against.
    unique = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return ", ".join(unique[:3])


async def lookup(latitude: float, longitude: float) -> str | None:
    """What is at this point, asking OpenStreetMap at most once a second."""
    global _last_call
    _load()
    key = _key(latitude, longitude)
    if key in _places:
        return _places[key]

    async with _lock:
        if key in _places:                              # filled while queueing
            return _places[key]
        wait = PAUSE - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = await client.get(NOMINATIM, params={
                    "lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 17,
                    "addressdetails": 1})
        except Exception as exc:                        # noqa: BLE001 - a coordinate still prints
            logger.info("reverse geocode failed for %s: %s", key, exc)
            return None
        finally:
            _last_call = time.monotonic()

        if response.status_code != 200:
            logger.info("reverse geocode for %s answered %s", key, response.status_code)
            return None
        body = response.json()
        place = _tidy(body.get("address") or {}) or (body.get("display_name") or "").split(",")[0]
        if not place:
            return None
        _places[key] = place
        if len(_places) > CACHE_MAX:
            for old in list(_places)[:len(_places) - CACHE_MAX]:
                _places.pop(old, None)
        _save()
        return place


async def fill(points: list[tuple[float, float]], limit: int = 60) -> dict[str, str]:
    """Learn up to `limit` unseen places and return everything known about these.

    The limit is what keeps a report that crosses a hundred new villages from
    holding someone at a spinner for two minutes; the rest keep their
    coordinates and are learned by the next report that needs them.
    """
    _load()
    found: dict[str, str] = {}
    budget = limit
    for latitude, longitude in points:
        key = _key(latitude, longitude)
        if key in _places:
            found[key] = _places[key]
            continue
        if budget <= 0:
            continue
        budget -= 1
        place = await lookup(latitude, longitude)
        if place:
            found[key] = place
    return found
