"""Missing VU mileage: distance a vehicle moved with no card in either slot.

Every card session in a vehicle unit carries the odometer reading at insertion
and at withdrawal, so the distance driven *on a card* is known exactly. When the
odometer at the next insertion is higher than the odometer at the last
withdrawal, the vehicle moved in between with no card in - the classic
"missing mileage" a DVSA examiner looks for: driving on no card, a card the
operator never collected, or a stretch nobody downloaded.

The figure is bounded to the gaps *between* recorded card sessions, not the
whole odometer span. A used vehicle's unit remembers mileage from before the
operator owned it; counting that would invent a breach. What is counted is only
movement that sits between two of this operator's own card sessions - provable,
and theirs to explain.

Crew is handled by merging both slots: the vehicle is covered whenever either
slot held a card, so a gap means neither did.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tacho import TachoFile
from app.services import archive, ddd_traconiq
from app.services.tacho_scope import TachoScope, reg_key

# Below this, an odometer step between withdrawal and the next insertion is
# yard shunting, fuelling or an MOT bay - not a road trip. The regulation cares
# about driving, so the noise floor keeps the report about real movement.
DEFAULT_THRESHOLD_KM = 3

# Banding on total unaccounted kilometres.
AMBER_AT = 1       # any proven missing mileage is worth a look
RED_AT = 50        # a day's driving or more with no card is a real finding


def _dedupe(sessions: list[dict]) -> list[dict]:
    """The same session appears in every download that overlaps it."""
    seen = set()
    out = []
    for s in sessions:
        key = (s["slot"], s["odo_in"], s["odo_out"],
               s["inserted"].isoformat() if s["inserted"] else None)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _merge(sessions: list[dict]) -> list[tuple[int, int, datetime | None, datetime | None]]:
    """Union of covered odometer intervals across both slots.

    Returns intervals (start_odo, end_odo, start_time, end_time) sorted by
    odometer, overlaps joined - so two drivers crewing the same stretch count
    once, and back-to-back sessions become one covered run.
    """
    spans = sorted(((s["odo_in"], s["odo_out"], s["inserted"], s["withdrawn"])
                    for s in sessions), key=lambda x: x[0])
    merged: list[list] = []
    for lo, hi, t0, t1 in spans:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
                merged[-1][3] = t1
        else:
            merged.append([lo, hi, t0, t1])
    return [tuple(m) for m in merged]


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def gaps_for(sessions: list[dict], threshold_km: int) -> list[dict]:
    """The unaccounted stretches, walking sessions in the order they happened.

    A high-water mark tracks the furthest odometer reading covered by a card so
    far. A session that opens above it means the vehicle moved there with no
    card in between - that step is missing mileage. A session that opens below
    it is either a crew mate sharing a stretch already covered, or a replacement
    unit reading lower after a swap; neither is movement to charge, so only
    forward steps count. Time order is what makes the swap safe: the lower
    reading arrives later and simply sits under the mark, inventing no gap.
    """
    ordered = sorted(sessions,
                     key=lambda s: (s["inserted"] or _EPOCH, s["odo_in"]))
    out: list[dict] = []
    high: int | None = None
    high_time = None
    for s in ordered:
        if high is None:
            high, high_time = s["odo_out"], s["withdrawn"]
            continue
        gap = s["odo_in"] - high
        if gap >= threshold_km:
            out.append({
                "from_odo": high, "to_odo": s["odo_in"], "km": gap,
                "from_time": high_time.isoformat() if high_time else None,
                "to_time": s["inserted"].isoformat() if s["inserted"] else None,
            })
        if s["odo_out"] > high:
            high, high_time = s["odo_out"], s["withdrawn"]
    return out


def _band(missing_km: int | None) -> str:
    if missing_km is None:
        return "grey"
    if missing_km >= RED_AT:
        return "red"
    return "amber" if missing_km >= AMBER_AT else "green"


async def missing_mileage(session: AsyncSession, scope: TachoScope,
                          threshold_km: int = DEFAULT_THRESHOLD_KM,
                          operator_name: str | None = None) -> list[dict]:
    """One row per vehicle: kilometres driven with no card, worst first."""
    files = (await session.execute(
        select(TachoFile).where(scope.files(), TachoFile.file_kind == "vehicle_unit",
                                TachoFile.parsed.is_(True)))).scalars().all()

    by_reg: dict[str, dict] = {}
    for tf in files:
        key = reg_key(tf.vehicle_ref)
        if not key:
            continue
        by_reg.setdefault(key, {"reg": tf.vehicle_ref, "sessions": []})
        try:
            parsed = ddd_traconiq.vu_sessions(archive.read(tf.storage_path))
        except Exception:
            # A file that will not re-parse is left out of the arithmetic rather
            # than counted as clean; it still shows on the download reports.
            continue
        if parsed.get("registration"):
            by_reg[key]["reg"] = parsed["registration"]
        by_reg[key]["sessions"].extend(parsed.get("sessions") or [])

    rows = []
    for data in by_reg.values():
        sessions = _dedupe(data["sessions"])
        if not sessions:
            rows.append({
                "registration": data["reg"], "sessions": 0, "band": "grey",
                "missing_km": None, "gap_count": 0, "biggest_gap_km": None,
                "covered_from": None, "covered_to": None, "covered_km": None,
                "first_seen": None, "last_seen": None, "gaps": [],
            })
            continue
        merged = _merge(sessions)
        gaps = gaps_for(sessions, threshold_km)
        missing = sum(g["km"] for g in gaps)
        covered_km = sum(hi - lo for lo, hi, _a, _b in merged)
        times = [s["inserted"] for s in sessions if s["inserted"]]
        rows.append({
            "registration": data["reg"],
            "sessions": len(sessions),
            "covered_from": merged[0][0],
            "covered_to": merged[-1][1],
            "covered_km": covered_km,
            "missing_km": missing,
            "gap_count": len(gaps),
            "biggest_gap_km": max((g["km"] for g in gaps), default=0),
            "first_seen": min(times).astimezone(timezone.utc).date().isoformat() if times else None,
            "last_seen": max(times).astimezone(timezone.utc).date().isoformat() if times else None,
            "band": _band(missing),
            "gaps": gaps,
        })

    # Worst first: most unaccounted kilometres at the top. "No data" rows sink
    # to the bottom - they are a parsing note, not a finding.
    rows.sort(key=lambda r: (r["missing_km"] is None, -(r["missing_km"] or 0), r["registration"]))
    return rows


def summarise(rows: list[dict]) -> dict:
    out = {"green": 0, "amber": 0, "red": 0, "grey": 0,
           "total": len(rows), "missing_km": 0}
    for r in rows:
        out[r["band"]] = out.get(r["band"], 0) + 1
        out["missing_km"] += r["missing_km"] or 0
    return out
