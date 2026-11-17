"""Clean Air Zone / ULEZ compliance and charge exposure.

UK Clean Air Zones and ULEZ share one minimum emissions standard: Euro 6 for
diesel, Euro 4 for petrol, and zero-emission vehicles are always compliant. So a
vehicle has a single CAZ compliance verdict; a non-compliant vehicle is
chargeable in every charging zone it enters (the charge varies by zone and
vehicle class). This module computes that verdict from DVLA data and lists the
UK charging zones with their daily charges as reference.

Charges/zones are indicative and change — verify against each authority before
quoting figures. Live zone-entry detection (needs Traccar positions) is a
separate follow-on; this is the emissions-compliance / charge-exposure view.
"""

from __future__ import annotations

import re

from app.models.vehicle import VehicleStatus

MIN_EURO_DIESEL = 6
MIN_EURO_PETROL = 4
ZERO_EMISSION_FUELS = {"ELECTRICITY", "ELECTRIC", "HYDROGEN"}

# Indicative UK charging zones (car/van and HGV/bus daily charges, GBP).
ZONES = [
    {"id": "london_ulez", "name": "London ULEZ", "kind": "charging",
     "car_van": 12.50, "hgv_bus": None,
     "note": "Greater London. HGVs/buses fall under the separate LEZ (£100–300/day)."},
    {"id": "birmingham", "name": "Birmingham CAZ (D)", "kind": "charging",
     "car_van": 8.00, "hgv_bus": 50.00, "note": "All vehicle types."},
    {"id": "bristol", "name": "Bristol CAZ (D)", "kind": "charging",
     "car_van": 9.00, "hgv_bus": 100.00, "note": "All vehicle types."},
    {"id": "sheffield", "name": "Sheffield CAZ (C)", "kind": "charging",
     "car_van": 10.00, "hgv_bus": 50.00, "note": "Vans/HGV/bus/coach/taxi; private cars exempt."},
    {"id": "bradford", "name": "Bradford CAZ (C+)", "kind": "charging",
     "car_van": 9.00, "hgv_bus": 50.00, "note": "Vans/HGV/bus/coach/taxi; private cars exempt."},
    {"id": "tyneside", "name": "Tyneside CAZ (C)", "kind": "charging",
     "car_van": 12.50, "hgv_bus": 50.00, "note": "Newcastle/Gateshead; vans/HGV/bus/taxi; cars exempt."},
    {"id": "portsmouth", "name": "Portsmouth CAZ (B)", "kind": "charging",
     "car_van": None, "hgv_bus": 50.00, "note": "Buses/coaches/HGV/taxi; cars & vans exempt."},
    {"id": "bath", "name": "Bath CAZ (C)", "kind": "charging",
     "car_van": 9.00, "hgv_bus": 100.00, "note": "Vans/HGV/bus/coach/taxi; private cars exempt."},
    {"id": "scotland_lez", "name": "Scottish LEZs", "kind": "penalty",
     "car_van": None, "hgv_bus": None,
     "note": "Glasgow/Edinburgh/Dundee/Aberdeen — non-compliant entry is a penalty (from £60), not a daily charge."},
]


def parse_euro(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"(\d)", value)
    return int(m.group(1)) if m else None


def compliance(vs: VehicleStatus) -> dict:
    """verdict in compliant | non_compliant | unknown, with a reason."""
    fuel = (vs.fuel_type or "").upper()
    if fuel in ZERO_EMISSION_FUELS:
        return {"verdict": "compliant", "reason": "Zero-emission vehicle."}
    euro = parse_euro(vs.euro_status)
    if euro is None or not fuel:
        return {"verdict": "unknown", "reason": "No Euro status / fuel type from DVLA yet."}
    if "DIESEL" in fuel:
        ok = euro >= MIN_EURO_DIESEL
        return {"verdict": "compliant" if ok else "non_compliant",
                "reason": f"Diesel Euro {euro} (min Euro {MIN_EURO_DIESEL})."}
    if "PETROL" in fuel or "HYBRID" in fuel or "GAS" in fuel:
        ok = euro >= MIN_EURO_PETROL
        return {"verdict": "compliant" if ok else "non_compliant",
                "reason": f"{fuel.title()} Euro {euro} (min Euro {MIN_EURO_PETROL})."}
    # unknown fuel: judge on the stricter diesel bar to be safe
    ok = euro >= MIN_EURO_DIESEL
    return {"verdict": "compliant" if ok else "non_compliant",
            "reason": f"{fuel.title()} Euro {euro}."}


def exposure(vehicles: list[VehicleStatus]) -> dict:
    rows = []
    for vs in vehicles:
        c = compliance(vs)
        rows.append({
            "reg": vs.reg, "make": vs.make, "fuel_type": vs.fuel_type,
            "euro_status": vs.euro_status, "verdict": c["verdict"], "reason": c["reason"],
        })
    order = {"non_compliant": 0, "unknown": 1, "compliant": 2}
    rows.sort(key=lambda r: order.get(r["verdict"], 9))
    summary = {
        "total": len(rows),
        "non_compliant": sum(1 for r in rows if r["verdict"] == "non_compliant"),
        "compliant": sum(1 for r in rows if r["verdict"] == "compliant"),
        "unknown": sum(1 for r in rows if r["verdict"] == "unknown"),
    }
    return {"summary": summary, "vehicles": rows, "zones": ZONES,
            "standard": {"diesel": MIN_EURO_DIESEL, "petrol": MIN_EURO_PETROL}}
