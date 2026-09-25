"""Standing accounts that see every vehicle on the platform.

Some accounts have to see the whole fleet: the owner's own login, and the
office address the alerts go to. Remembering to tick a new lorry onto each of
them by hand is the sort of job that gets forgotten, and the failure is silent
- the vehicle simply is not there when somebody goes looking for it.

So rather than hooking the moment a vehicle is created, this reconciles: it
asks what exists, asks what each standing account can see, and grants the
difference. That catches a vehicle however it arrived - the web app, the label
photos, an import, or the API - and a vehicle that was granted already costs
nothing to check.

An account that is a DH FleetView administrator is left alone: it already sees
everything, and granting it individual vehicles would be noise.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.services import auth

logger = logging.getLogger("tacho.access")

# What was found last time round, for the schedule screen.
last_result: dict = {"ran": False, "why": "has not run yet"}


def emails() -> list[str]:
    """The addresses that should see the whole fleet."""
    return [e.strip() for e in (settings.auto_share_emails or "").split(",") if e.strip()]


def _key(address: str) -> str:
    return address.strip().lower()


async def reconcile(principal) -> dict:
    """Give every standing account every vehicle it is missing."""
    wanted = emails()
    if not wanted:
        return {"ran": False, "why": "no accounts are set to see the whole fleet"}

    users = await auth.traccar_get(principal, "/api/users")
    if users is None:
        return {"ran": False, "why": "DH FleetView would not answer; check the API token"}
    devices = await auth.traccar_get(principal, "/api/devices?all=true")
    if devices is None:
        return {"ran": False, "why": "the vehicle list could not be read"}

    all_ids = {d["id"] for d in devices if isinstance(d, dict) and d.get("id")}
    by_email = {_key(u.get("email") or ""): u for u in users if isinstance(u, dict)}

    granted, problems, accounts = [], [], []
    for address in wanted:
        user = by_email.get(_key(address))
        if user is None:
            problems.append({"account": address,
                             "why": "no DH FleetView account has that address"})
            continue
        if user.get("administrator"):
            accounts.append({"account": address, "vehicles": len(all_ids),
                             "note": "an administrator, so it already sees every vehicle"})
            continue

        theirs = await auth.traccar_get(principal, f"/api/devices?userId={user['id']}")
        if theirs is None:
            problems.append({"account": address, "why": "their vehicle list could not be read"})
            continue
        missing = sorted(all_ids - {d["id"] for d in theirs if isinstance(d, dict) and d.get("id")})

        added = []
        for device_id in missing:
            try:
                await auth.traccar_send(principal, "POST", "/api/permissions",
                                        {"userId": user["id"], "deviceId": device_id})
                added.append(device_id)
            except Exception as exc:  # noqa: BLE001 - one refusal must not stop the rest
                logger.warning("could not give vehicle %s to %s: %s", device_id, address, exc)
                problems.append({"account": address, "device_id": device_id, "why": str(exc)})

        if added:
            names = {d["id"]: d.get("name") for d in devices if isinstance(d, dict)}
            logger.info("gave %d new vehicle(s) to %s: %s", len(added), address,
                        ", ".join(str(names.get(i) or i) for i in added))
            granted.append({"account": address, "added": len(added),
                            "vehicles": [names.get(i) or i for i in added]})
        accounts.append({"account": address, "vehicles": len(all_ids) - len(missing) + len(added)})

    return {"ran": True, "fleet": len(all_ids), "accounts": accounts,
            "granted": granted, "problems": problems}


async def run(principal) -> dict:
    global last_result
    last_result = await reconcile(principal)
    return last_result
