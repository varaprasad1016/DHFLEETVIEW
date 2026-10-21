"""Earned Recognition style KPI dashboard: maintenance and drivers' hours measures
in 4-week periods, from data the compliance suite already holds.

Targets are the operator's own (editable). The starting values are suggestions:
check them against the current DVSA Earned Recognition KPI guidance.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infringement_review import InfringementReview
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule
from app.models.settings import AppSetting
from app.models.shifts import Shift
from app.models.tacho import Infringement, TachoFile
from app.models.tacho_live import TachoLiveAlert
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect
from app.services.tacho_scope import reg_key

LONDON = ZoneInfo("Europe/London")
PERIOD_DAYS = 28

# code: (group, label, unit, direction, suggested target, explanation)
KPIS: dict[str, tuple[str, str, str, str, float, str]] = {
    "pmi_on_time": ("Maintenance", "Safety inspections done on time", "%", "min", 100,
                    "Inspections recorded in the period that were done by their planned date."),
    "mot_first_time_pass": ("Maintenance", "MOT / annual test first-time pass", "%", "min", 95,
                            "MOT records in the period with a pass or pass with advisories."),
    "walkaround_coverage": ("Maintenance", "Shifts with a pre-use walkaround check", "%", "min", 100,
                            "App shifts started in the period that have a pre-use check."),
    "dangerous_defects_fixed_24h": ("Maintenance", "Dangerous defects rectified within 24 hours", "%", "min", 100,
                                    "Dangerous driver-reported defects raised in the period, fixed within a day."),
    "card_downloads_on_time": ("Drivers' hours", "Driver cards downloaded within 28 days", "%", "min", 98,
                               "Your drivers with card data whose last download at the period end was within 28 days."),
    "vu_downloads_on_time": ("Drivers' hours", "Vehicle units downloaded within 90 days", "%", "min", 98,
                             "Your vehicles with unit data whose last download at the period end was within 90 days."),
    "serious_infringements_per_driver": ("Drivers' hours", "Serious infringements per driver", "per driver", "max", 0.5,
                                         "Serious and very serious infringements starting in the period, per driver with card data."),
    "infringements_debriefed": ("Drivers' hours", "Infringements debriefed", "%", "min", 100,
                                "Infringements starting in the period with an office debrief recorded."),
    "no_card_driving": ("Drivers' hours", "Driving without a card (live alerts)", "events", "max", 0,
                        "Times a tracked vehicle was driven without a driver card."),
}
TARGETS_DEFAULT_KEY = "er_targets:default"


def periods(count: int = 13, today: date | None = None) -> list[tuple[date, date]]:
    """4-week periods (Monday to Sunday), newest first, the newest ending last Sunday."""
    today = today or datetime.now(LONDON).date()
    end = today - timedelta(days=today.weekday() + 1)      # the last Sunday before today: periods are complete
    out = []
    for _ in range(count):
        start = end - timedelta(days=PERIOD_DAYS - 1)
        out.append((start, end))
        end = start - timedelta(days=1)
    return out


def _utc(d: date, end: bool = False) -> datetime:
    return datetime.combine(d + timedelta(days=1) if end else d, time(0), LONDON).astimezone(timezone.utc)


def _pct(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


async def targets_for(session: AsyncSession, user_id: int | None) -> tuple[dict[str, float], str]:
    for key, source in ((f"er_targets:user:{user_id}" if user_id is not None else None, "yours"), (TARGETS_DEFAULT_KEY, "default")):
        if key is None:
            continue
        row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if row is not None and isinstance(row.value, dict):
            merged = {code: float(row.value.get(code, spec[4])) for code, spec in KPIS.items()}
            return merged, source
    return {code: float(spec[4]) for code, spec in KPIS.items()}, "suggested"


def _met(code: str, value: float | None, target: float) -> bool | None:
    if value is None:
        return None
    return value >= target if KPIS[code][3] == "min" else value <= target


async def dashboard(session: AsyncSession, tacho_scope, record_scope, vehicle_ids: list[int], targets: dict[str, float],
                    count: int = 13, today: date | None = None, period_list: list[tuple[date, date]] | None = None) -> dict:
    """KPIs per period (newest first). period_list overrides the 4-week periods (e.g. one custom range)."""
    today = today or datetime.now(LONDON).date()
    plist = period_list or periods(count, today)
    oldest = _utc(plist[-1][0])
    newest_end = _utc(plist[0][1], end=True)

    # --- data, loaded once -------------------------------------------------------------------
    pmis = (await session.execute(select(MaintenanceRecord.kind, MaintenanceRecord.performed_on, MaintenanceRecord.due_on,
                                         MaintenanceRecord.result).where(
        MaintenanceRecord.traccar_device_id.in_(vehicle_ids or [-1]),
        MaintenanceRecord.performed_on >= plist[-1][0]))).all()
    shifts = (await session.execute(select(Shift.id, Shift.clocked_in_at, Shift.vehicle_reg).where(
        record_scope.condition(Shift), Shift.clocked_in_at >= oldest, Shift.clocked_in_at < newest_end))).all()
    checks = (await session.execute(select(WalkaroundCheck.shift_id, WalkaroundCheck.vehicle_reg, WalkaroundCheck.created_at).where(
        record_scope.condition(WalkaroundCheck), WalkaroundCheck.phase == "pre_use",
        WalkaroundCheck.created_at >= oldest - timedelta(days=1)))).all()
    defects = (await session.execute(select(WalkaroundDefect.created_at, WalkaroundDefect.rectified_at)
        .join(WalkaroundCheck, WalkaroundCheck.id == WalkaroundDefect.check_id).where(
        record_scope.condition(WalkaroundCheck), WalkaroundDefect.severity == "dangerous",
        WalkaroundDefect.created_at >= oldest))).all()
    from app.services.tacho_compliance import download_time
    files = (await session.execute(select(TachoFile.file_kind, TachoFile.driver_ref, TachoFile.vehicle_ref, download_time())
                                   .where(tacho_scope.files()))).all()
    infringements = (await session.execute(select(Infringement.id, Infringement.severity, Infringement.period_start,
                                                  Infringement.driver_ref).where(
        tacho_scope.infringements(), Infringement.status != "dismissed", Infringement.period_start >= oldest))).all()
    debriefed = set((await session.execute(select(InfringementReview.infringement_id).where(
        InfringementReview.debriefed_at.is_not(None)))).scalars().all())
    alerts = [a for a in (await session.execute(select(TachoLiveAlert).where(
        TachoLiveAlert.kind == "no_card_driving", TachoLiveAlert.started_at >= oldest))).scalars().all()
        if tacho_scope.allows_live(a.card_number, a.vehicle_reg, a.device_uid)]

    from sqlalchemy import func as sa_func

    from app.models.tacho_live import TachoLiveActivity
    firsts = (await session.execute(select(TachoLiveActivity.device_uid, TachoLiveActivity.vehicle_reg,
                                           sa_func.min(TachoLiveActivity.started_at))
                                    .group_by(TachoLiveActivity.device_uid, TachoLiveActivity.vehicle_reg))).all()
    tracked_since = min((first for uid, reg, first in firsts if tacho_scope.allows_live(None, reg, uid)), default=None)

    card_downloads: dict[str, list[datetime]] = {}
    vu_downloads: dict[str, list[datetime]] = {}
    for kind, dref, vref, created in files:
        if kind == "driver_card" and dref:
            card_downloads.setdefault(dref, []).append(created)
        elif kind == "vehicle_unit" and vref:
            vu_downloads.setdefault(reg_key(vref), []).append(created)

    def on_time_share(downloads: dict[str, list[datetime]], at: datetime, window_days: int) -> float | None:
        known = [times for times in downloads.values() if min(times) <= at]
        if not known:
            return None
        ok = sum(1 for times in known if (at - max(t for t in times if t <= at)).days <= window_days)
        return _pct(ok, len(known))

    rows: dict[str, list] = {code: [] for code in KPIS}
    for start, end in plist:
        s_utc, e_utc = _utc(start), _utc(end, end=True)
        in_p = lambda t: s_utc <= t < e_utc  # noqa: E731

        p_pmis = [r for r in pmis if r.kind == "pmi" and start <= r.performed_on <= end and r.due_on is not None]
        rows["pmi_on_time"].append(_pct(sum(1 for r in p_pmis if r.performed_on <= r.due_on), len(p_pmis)))
        p_mots = [r for r in pmis if r.kind == "mot" and start <= r.performed_on <= end and r.result]
        rows["mot_first_time_pass"].append(_pct(sum(1 for r in p_mots if r.result in ("pass", "advisories")), len(p_mots)))

        p_shifts = [sh for sh in shifts if in_p(sh.clocked_in_at)]
        covered = 0
        for sh in p_shifts:
            local_day = sh.clocked_in_at.astimezone(LONDON).date()
            if any(c.shift_id == sh.id or (c.vehicle_reg and sh.vehicle_reg and reg_key(c.vehicle_reg) == reg_key(sh.vehicle_reg)
                                           and c.created_at.astimezone(LONDON).date() == local_day) for c in checks):
                covered += 1
        rows["walkaround_coverage"].append(_pct(covered, len(p_shifts)))

        p_def = [d for d in defects if in_p(d.created_at)]
        rows["dangerous_defects_fixed_24h"].append(_pct(
            sum(1 for d in p_def if d.rectified_at and d.rectified_at - d.created_at <= timedelta(hours=24)), len(p_def)))

        rows["card_downloads_on_time"].append(on_time_share(card_downloads, e_utc, 28))
        rows["vu_downloads_on_time"].append(on_time_share(vu_downloads, e_utc, 90))

        p_inf = [i for i in infringements if in_p(i.period_start)]
        drivers_with_data = len({i.driver_ref for i in p_inf} | {r for r, times in card_downloads.items() if min(times) < e_utc})
        serious = sum(1 for i in p_inf if i.severity in ("serious", "very_serious"))
        rows["serious_infringements_per_driver"].append(round(serious / drivers_with_data, 2) if drivers_with_data else None)
        rows["infringements_debriefed"].append(_pct(sum(1 for i in p_inf if i.id in debriefed), len(p_inf)))
        # No tracked vehicles yet (or not in this period): no data, rather than a clean zero.
        rows["no_card_driving"].append(sum(1 for a in alerts if in_p(a.started_at))
                                       if tracked_since is not None and tracked_since < e_utc else None)

    kpis = []
    for code, (group, label, unit, direction, _suggested, explain) in KPIS.items():
        values = rows[code]
        target = targets[code]
        latest = next((v for v in values if v is not None), None)
        kpis.append({"code": code, "group": group, "label": label, "unit": unit, "direction": direction,
                     "target": target, "explanation": explain, "values": values,
                     "met": [_met(code, v, target) for v in values], "latest": latest,
                     "latest_met": _met(code, latest, target)})

    overdue_now = (await session.execute(select(MaintenanceSchedule.id).where(
        MaintenanceSchedule.traccar_device_id.in_(vehicle_ids or [-1]), MaintenanceSchedule.active.is_(True),
        MaintenanceSchedule.next_due < today))).all()
    return {
        "periods": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in plist],
        "kpis": kpis,
        "now": {"inspections_overdue": len(overdue_now)},
    }
