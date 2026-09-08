"""Compute MOT/tax reminder state for a monitored vehicle from its DVLA data."""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.models.vehicle import VehicleStatus


def normalize_reg(reg: str) -> str:
    return (reg or "").strip().upper().replace(" ", "")


def _state(due: date | None, ok_status: bool, today: date) -> tuple[str, int | None]:
    """Return (state, days_left). state in ok|due_soon|overdue|unknown."""
    if due is None:
        if ok_status is False:
            return ("overdue", None)
        if ok_status is True:
            return ("ok", None)
        return ("unknown", None)
    days = (due - today).days
    if days < 0 or ok_status is False:
        return ("overdue", days)
    if days <= settings.reminder_due_soon_days:
        return ("due_soon", days)
    return ("ok", days)


def vehicle_view(vs: VehicleStatus, today: date | None = None) -> dict:
    today = today or date.today()
    mot_ok = (vs.mot_status or "").lower().startswith("valid") if vs.mot_status else None
    tax_ok = (vs.tax_status or "").lower() == "taxed" if vs.tax_status else None
    mot_state, mot_days = _state(vs.mot_expiry_date, mot_ok, today)
    tax_state, tax_days = _state(vs.tax_due_date, tax_ok, today)
    order = {"overdue": 0, "due_soon": 1, "unknown": 2, "ok": 3}
    overall = min([mot_state, tax_state], key=lambda s: order.get(s, 9))
    return {
        "reg": vs.reg, "make": vs.make, "colour": vs.colour, "year": vs.year,
        "fuel_type": vs.fuel_type, "euro_status": vs.euro_status, "co2": vs.co2,
        "tax_status": vs.tax_status, "tax_due_date": vs.tax_due_date.isoformat() if vs.tax_due_date else None,
        "tax_state": tax_state, "tax_days": tax_days,
        "mot_status": vs.mot_status, "mot_expiry_date": vs.mot_expiry_date.isoformat() if vs.mot_expiry_date else None,
        "mot_state": mot_state, "mot_days": mot_days,
        "overall": overall,
        "last_checked": vs.last_checked.isoformat() if vs.last_checked else None,
        "check_error": vs.check_error,
    }
