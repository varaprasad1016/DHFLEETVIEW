"""Tacho compliance API: download-window status, .ddd archive/upload, and the
drivers'-hours / WTD infringement engine. Every route is licence-gated.
"""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.services.auth import Principal
from app.config import settings
from app.database import get_session
from app.models.core import Company, Vehicle
from app.models.tacho import TachoActivity
from app.models.operator import Operator
from app.models.tacho import Infringement, TachoFile
from app.services import (archive, ddd_go, ddd_parser, ddd_traconiq, driver_calendar, driver_reports,
                          infringement_reviews, mailer,
                          media_store, modules, operators, report_settings,
                          tacho_compliance, tacho_pdf, tacho_report)
from app.services import wtd as wtd_service
from app.models.infringement_review import InfringementReview
from app.services.tacho_scope import TachoScope, scope_for
from app.services.tacho_rules import Activity, Infringement as RuleInfringement, analyse
from app.services.tacho_rules import code_for as tacho_rules_codes

router = APIRouter(prefix="/api/tacho", tags=["tacho"], dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("tacho"))])


# --- schemas ----------------------------------------------------------------

class ActivityIn(BaseModel):
    type: str = Field(pattern="^(drive|work|available|rest)$")
    start: datetime
    end: datetime


class AnalyzeIn(BaseModel):
    driver_ref: str
    activities: list[ActivityIn]
    source_file_id: uuid.UUID | None = None


class UploadIn(BaseModel):
    filename: str
    content_base64: str
    file_kind: str = Field(default="driver_card", pattern="^(driver_card|vehicle_unit|unknown)$")
    driver_ref: str | None = None
    vehicle_ref: str | None = None
    company_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|dismissed)$")


class DebriefIn(BaseModel):
    action: str
    notes: str | None = Field(default=None, max_length=4000)


class ReportSettingsIn(BaseModel):
    hidden: list[str] = []                # rule codes left off the weekly report
    for_everyone: bool = False            # super administrator: save as everyone's default


class ReanalyseIn(BaseModel):
    file_id: uuid.UUID | None = None      # one file, or every archived card
    replace_open: bool = True             # drop the previous run's open rows


# --- helpers ----------------------------------------------------------------

async def tacho_scope(principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)) -> TachoScope:
    """The tachograph data this office user may see (see services/tacho_scope)."""
    import urllib.error

    try:
        return await scope_for(session, principal)
    except (urllib.error.URLError, OSError, ValueError):
        raise HTTPException(status_code=503, detail="Can't reach DH FleetView to check your drivers. Try again shortly.")


def _super_admin_only(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only the super administrator can do this.")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _account_company(session: AsyncSession, x_company_id: str | None = None) -> Company | None:
    """Resolve the tenant from the account context, never from the upload form.

    The authenticated account will eventually supply this context directly. For
    the current single-deployment setup it is supplied by TACHO_ACCOUNT_COMPANY_ID;
    if that is blank, one active company is an unambiguous safe default.
    """
    # The deployment/account configuration is the tenant boundary. The upload
    # form and request headers cannot select another company.
    raw = (settings.tacho_account_company_id or "").strip()
    if raw:
        try:
            company_id = uuid.UUID(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Account company ID is not a valid UUID.") from exc
        company = await session.get(Company, company_id)
        if company is None or not company.active:
            raise HTTPException(status_code=404, detail="Account company not found or inactive.")
        return company

    companies = (await session.execute(
        select(Company).where(Company.active.is_(True)).order_by(Company.created_at)
    )).scalars().all()
    if len(companies) == 1:
        return companies[0]
    if len(companies) > 1:
        raise HTTPException(
            status_code=409,
            detail="This account is not linked to a single customer company. Configure TACHO_ACCOUNT_COMPANY_ID.",
        )
    return None


def _same_registration(left: str | None, right: str | None) -> bool:
    return bool(left and right and "".join(left.upper().split()) == "".join(right.upper().split()))


def _full_readers():
    """The readers that implement the whole regulation, best first.

    tachoparser leads because it is the only one that reads second-generation
    version 1 units. tachograph-go follows: it is MIT, so it keeps working on
    an installation that would rather not ship AGPL code at all.
    """
    return (
        (ddd_traconiq.parse_driver_card, ddd_traconiq.PARSER_NAME, ddd_traconiq.available),
        (ddd_go.parse_driver_card, "tachograph-go", ddd_go.available),
    )


def _parse_driver_card(data: bytes) -> tuple[dict, str]:
    """Parse with the best available reader, falling back only when configured.

    A failed parse is not silently hidden when fallback is disabled: the caller
    records the error with the archived file. This makes deployments able to
    enforce Gen2/signature-capable parsing rather than accidentally accepting
    the old screening reader.
    """
    failures: list[str] = []
    for reader, name, installed in _full_readers():
        if not installed():
            failures.append(f"{name}: not installed")
            continue
        try:
            return reader(data), name
        except Exception as exc:                            # noqa: BLE001
            failures.append(f"{name}: {exc}")

    reasons = "; ".join(failures)
    if not settings.tacho_parser_fallback:
        raise ValueError(f"no capable parser read this card - {reasons}")

    try:
        return ddd_parser.parse_driver_card(data), "builtin-gen1"
    except Exception as fallback_error:
        raise ValueError(
            f"{reasons}; built-in parser failed: {fallback_error}") from fallback_error


def parse_vehicle_unit(data: bytes) -> dict:
    """Parse a vehicle unit with the best available reader.

    There is no built-in fallback here: the Gen1 reader was only ever written
    for cards. Both full readers are tried because they fail on different
    files - tachograph-go cannot read second-generation version 1 units, and a
    file one reader stumbles on may still be readable by the other.
    """
    failures: list[str] = []
    for module, name in ((ddd_traconiq, ddd_traconiq.PARSER_NAME),
                         (ddd_go, "tachograph-go")):
        if not module.available():
            failures.append(f"{name}: not installed")
            continue
        try:
            return module.parse_vehicle_unit(data)
        except Exception as exc:                            # noqa: BLE001
            failures.append(f"{name}: {exc}")
    raise ValueError("no parser read this vehicle unit - " + "; ".join(failures))


def _vehicle_ref_for(parsed: dict, activity: Activity, fallback: str | None = None) -> str | None:
    """Which lorry the card says the driver was in when this span began.

    The spells are chronological, so the right one is the latest that had
    started by the time the activity did - not merely the first one that
    overlaps. A spell whose end the card does not record (the newest is open,
    and an older one can have an unreadable end) satisfies a loose overlap
    test for everything that follows it, which put a whole card's 276 spans in
    one lorry while the card plainly named a dozen.

    A span that begins before any spell - rest before the driver ever boarded -
    gets no registration rather than the nearest guess. The driver was not in
    a lorry, and saying which one would be an invention.
    """
    best = None
    for vehicle in parsed.get("vehicles", []):
        if not vehicle.first_use or vehicle.first_use > activity.start:
            continue
        # A spell the card closed cannot own work that started after it ended.
        if vehicle.last_use is not None and activity.start > vehicle.last_use:
            continue
        if best is None or vehicle.first_use > best.first_use:
            best = vehicle
    if best is not None and best.registration:
        return best.registration
    return fallback


async def _persist_activities(session: AsyncSession, parsed: dict, source_file_id: uuid.UUID,
                              company_id: uuid.UUID | None = None, vehicle_id: uuid.UUID | None = None,
                              vehicle_ref: str | None = None, driver_ref: str | None = None,
                              activity_driver_refs: list[str | None] | None = None) -> None:
    """Replace the canonical spans for one source file after a successful parse."""
    await session.execute(delete(TachoActivity).where(TachoActivity.source_file_id == source_file_id))
    for index, activity in enumerate(parsed.get("activities", [])):
        activity_driver_ref = (
            activity_driver_refs[index]
            if activity_driver_refs is not None and index < len(activity_driver_refs)
            else None
        )
        session.add(TachoActivity(
            company_id=company_id, source_file_id=source_file_id,
            driver_ref=activity_driver_ref or driver_ref or parsed.get("driver_ref"),
            vehicle_id=vehicle_id,
            vehicle_ref=_vehicle_ref_for(parsed, activity, vehicle_ref),
            activity_type=activity.type, started_at=activity.start, ended_at=activity.end,
            crew=activity.crew,
            source="TACHOGRAPH", confidence="DIRECT"))
    await session.flush()


async def _persist_infringements(session: AsyncSession, driver_ref: str, found: list,
                                 source_file_id: uuid.UUID, company_id: uuid.UUID | None = None) -> int:
    if not found:
        return 0
    keys = [f"{driver_ref}|{i.rule}|{i.start.isoformat()}" for i in found]
    existing = set((await session.execute(
        select(Infringement.dedup_key).where(Infringement.dedup_key.in_(keys))
    )).scalars().all())
    added = 0
    for inf, key in zip(found, keys):
        if key in existing:
            continue
        session.add(Infringement(
            driver_ref=driver_ref, rule=inf.rule, title=inf.title, severity=inf.severity,
            period_start=inf.start, period_end=inf.end, detail=inf.detail,
            limit_minutes=inf.limit_minutes, actual_minutes=inf.actual_minutes,
            source_file_id=source_file_id, company_id=company_id, dedup_key=key))
        existing.add(key)
        added += 1
    await session.commit()
    return added


# The rules that judge what the driver did with their card, rather than how
# long they drove. A country entry and a card withdrawal live on the card and
# nowhere else, so these are the card's to answer for and a vehicle unit must
# never be asked about them. Keeping the two families apart is what lets the
# combined analysis and the card's own analysis both run without one deleting
# the other's findings.
RECORD_KEEPING_RULES = ("country_start", "country_end", "card_withdrawal")


async def _clear_open(session: AsyncSession, driver_ref: str,
                      company_id: uuid.UUID | None, rules: tuple[str, ...],
                      keep_rules: bool, within: tuple[datetime, datetime] | None = None) -> None:
    """Drop this driver's untouched findings for one family of rules.

    Anything acknowledged, dismissed, signed or debriefed is somebody's
    decision on the record and is left exactly as they left it.
    """
    reviewed = select(InfringementReview.infringement_id)
    stale = delete(Infringement).where(
        Infringement.driver_ref == driver_ref,
        Infringement.status == "open",
        Infringement.id.not_in(reviewed),
        Infringement.rule.in_(rules) if keep_rules else Infringement.rule.not_in(rules))
    if company_id is not None:
        stale = stale.where(Infringement.company_id == company_id)
    if within is not None:
        stale = stale.where(Infringement.period_start >= within[0],
                            Infringement.period_start <= within[1])
    await session.execute(stale)
    await session.flush()


async def analyse_card_records(session: AsyncSession, driver_ref: str, parsed: dict,
                               source_file_id: uuid.UUID,
                               company_id: uuid.UUID | None = None) -> int:
    """Judge a driver card on the things only a card can answer for.

    The country entries and the card's time out of a unit, over the period this
    card covers. The hours themselves are left to `analyse_driver`, which has
    the driver's whole timeline rather than one card's worth of it.
    """
    activities = parsed.get("activities") or []
    places = parsed.get("places")
    if not activities or places is None:
        return 0

    found = [i for i in analyse(activities, places, parsed.get("card_gaps"))
             if i.rule in RECORD_KEEPING_RULES]

    # Scoped to what this card actually covers, so a driver's older card does
    # not have its findings cleared by a newer one that says nothing about
    # those weeks.
    covered = (min(a.start for a in activities), max(a.end for a in activities))
    await _clear_open(session, driver_ref, company_id, RECORD_KEEPING_RULES,
                      keep_rules=True, within=covered)
    if not found:
        await session.commit()
        return 0
    return await _persist_infringements(session, driver_ref, found, source_file_id, company_id)


async def analyse_driver(session: AsyncSession, driver_ref: str,
                         company_id: uuid.UUID | None = None,
                         source_file_id: uuid.UUID | None = None) -> int:
    """Run the rules over everything known about one driver, and record what they find.

    A vehicle unit holds the vehicle's record, not a driver's, so analysing one
    file on its own judges a driver on the hours they happened to do in that
    lorry. This assembles the driver's whole timeline from every file first -
    which is the only way the daily and weekly limits mean anything - and then
    runs the rules once over the lot.

    The record-keeping rules are left out deliberately: a country entry lives
    on the driver's own card, so judging it from vehicle data would report
    every day as missing one. `analyse` already skips them when no places are
    supplied.

    Findings nobody has looked at yet are replaced rather than added to. A
    re-read happens because the reading improved, and an infringement the data
    no longer supports has to be able to disappear. Anything somebody has
    already acknowledged or dismissed is left exactly as they left it: that is
    their decision on the record, not ours to revise.
    """
    if not driver_ref:
        return 0

    query = select(TachoActivity).where(TachoActivity.driver_ref == driver_ref)
    if company_id is not None:
        query = query.where(TachoActivity.company_id == company_id)
    rows = (await session.execute(query.order_by(TachoActivity.started_at))).scalars().all()
    if not rows:
        return 0

    await _clear_open(session, driver_ref, company_id, RECORD_KEEPING_RULES,
                      keep_rules=False)

    timeline = [Activity(row.activity_type, row.started_at, row.ended_at, crew=row.crew)
                for row in rows]
    # The record-keeping rules belong to the card, which is the only thing that
    # knows about them; `analyse` already leaves them out when given no places,
    # and this makes that explicit rather than incidental.
    found = [i for i in analyse(timeline) if i.rule not in RECORD_KEEPING_RULES]
    if not found:
        await session.commit()
        return 0

    file_id = source_file_id or rows[-1].source_file_id
    return await _persist_infringements(session, driver_ref, found, file_id, company_id)


# --- endpoints --------------------------------------------------------------

@router.get("/company")
async def company_name(session: AsyncSession = Depends(get_session),
                       scope: TachoScope = Depends(tacho_scope)) -> dict:
    """Return the latest company name read from one of your vehicle-unit uploads."""
    return {"name": await _latest_company_name(session, scope)}


def _reg_key(value: str | None) -> str:
    return "".join(str(value or "").upper().split())


async def _operator_for_report(session: AsyncSession, parsed: dict,
                               start: date | None, end: date | None) -> dict:
    """Whose name belongs on this driver's report.

    Worked out from the vehicles the driver actually drove in the period, which
    is the only honest source: a driver card carries no operator of its own,
    and taking the most recent upload on the account puts whoever downloaded
    last on everybody's paperwork.

    Where the vehicles driven belong to more than one operator, no name is
    chosen. That is a real situation - a driver can work for two firms in a
    week - and picking one of them would be worse than leaving it blank,
    because the report would look authoritative and be wrong.
    """
    driven: set[str] = set()
    for spell in parsed.get("vehicles") or []:
        if not spell.registration:
            continue
        day = (spell.first_use or spell.last_use)
        if day is not None:
            if start is not None and day.date() < start:
                continue
            if end is not None and day.date() > end:
                continue
        driven.add(_reg_key(spell.registration))

    if not driven:
        return {"name": None, "operators": [], "vehicles": [], "unknown": []}

    rows = (await session.execute(
        select(Vehicle.registration, Operator.name)
        .outerjoin(Operator, Operator.id == Vehicle.operator_id)
        .where(Vehicle.registration.in_(driven)))).all()
    known = {_reg_key(reg): name for reg, name in rows if name}
    names = sorted(set(known.values()))
    unknown = sorted(driven - set(known))

    return {
        # One operator across every vehicle we can identify, or nothing.
        "name": names[0] if len(names) == 1 else None,
        "operators": names,
        "vehicles": sorted(driven),
        "unknown": unknown,
        "spans_operators": len(names) > 1,
    }


async def _latest_company_name(session: AsyncSession, scope: TachoScope) -> str | None:
    return (await session.execute(
        select(TachoFile.company_name)
        .where(TachoFile.file_kind == "vehicle_unit", TachoFile.company_name.isnot(None), scope.files())
        .order_by(TachoFile.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


@router.get("/drivers")
async def list_drivers(session: AsyncSession = Depends(get_session),
                       scope: TachoScope = Depends(tacho_scope)) -> list[dict]:
    """Every driver the tachograph data knows about, however it learned of them.

    The pages used to build their own list from driver-card files alone, which
    meant a driver whose hours came off a vehicle unit could not be picked on
    the weekly report or the timeline - the data was all there and there was no
    way to ask for it. A vehicle unit names the drivers who used it, so they
    belong on this list on the same footing as a card holder; which evidence
    there is for each is said rather than implied, because a driver known only
    from a unit has no country entries and the reports should say so.
    """
    rows = (await session.execute(
        select(TachoActivity.driver_ref,
               TachoFile.file_kind,
               func.count(TachoActivity.id),
               func.min(TachoActivity.started_at),
               func.max(TachoActivity.ended_at))
        .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
        .where(TachoActivity.driver_ref.is_not(None), scope.activities())
        .group_by(TachoActivity.driver_ref, TachoFile.file_kind))).all()

    found: dict[str, dict] = {}
    for driver_ref, kind, spans, first, last in rows:
        entry = found.setdefault(driver_ref, {
            "driver_ref": driver_ref, "spans": 0,
            "from_card": False, "from_vehicle_unit": False,
            "first_seen": first, "last_seen": last,
        })
        entry["spans"] += spans
        entry["from_card"] |= kind == "driver_card"
        entry["from_vehicle_unit"] |= kind == "vehicle_unit"
        entry["first_seen"] = min(entry["first_seen"], first)
        entry["last_seen"] = max(entry["last_seen"], last)

    return [{
        **entry,
        "first_seen": entry["first_seen"].isoformat() if entry["first_seen"] else None,
        "last_seen": entry["last_seen"].isoformat() if entry["last_seen"] else None,
        # What the hours rest on, so a report can be honest about its evidence.
        "evidence": ("card and vehicle unit" if entry["from_card"] and entry["from_vehicle_unit"]
                     else "driver card" if entry["from_card"] else "vehicle unit"),
    } for entry in sorted(found.values(), key=lambda e: e["driver_ref"])]


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session),
                  scope: TachoScope = Depends(tacho_scope)) -> dict:
    comp = await tacho_compliance.compliance(session, scope=scope)
    open_inf = (await session.execute(
        select(func.count()).select_from(Infringement).where(Infringement.status == "open", scope.infringements())
    )).scalar_one()
    serious = (await session.execute(
        select(func.count()).select_from(Infringement).where(
            Infringement.status == "open", Infringement.severity.in_(("serious", "very_serious")),
            scope.infringements())
    )).scalar_one()
    files = (await session.execute(select(func.count()).select_from(TachoFile).where(scope.files()))).scalar_one()
    d = comp["summary"]["drivers"]
    v = comp["summary"]["vehicles"]
    return {
        "open_infringements": open_inf,
        "open_serious": serious,
        "archived_files": files,
        "drivers_overdue": d.get("overdue", 0) + d.get("no_data", 0),
        "vehicles_overdue": v.get("overdue", 0) + v.get("no_data", 0),
    }


@router.get("/compliance")
async def compliance(session: AsyncSession = Depends(get_session),
                     scope: TachoScope = Depends(tacho_scope)) -> dict:
    return await tacho_compliance.compliance(session, scope=scope)


@router.post("/analyze")
async def analyze(body: AnalyzeIn, session: AsyncSession = Depends(get_session),
                  principal: Principal = Depends(require_manager)) -> dict:
    _super_admin_only(principal)
    acts = [Activity(a.type, _aware(a.start), _aware(a.end)) for a in body.activities]
    found = analyse(acts)
    added = await _persist_infringements(session, body.driver_ref, found, body.source_file_id)
    return {
        "driver_ref": body.driver_ref,
        "activities": len(acts),
        "infringements_found": len(found),
        "infringements_new": added,
        "results": [i.to_dict(body.driver_ref) for i in found],
    }


@router.post("/upload", status_code=201)
async def upload(body: UploadIn, session: AsyncSession = Depends(get_session),
                 x_company_id: str | None = Header(default=None),
                 principal: Principal = Depends(require_manager),
                 scope: TachoScope = Depends(tacho_scope)) -> dict:
    filename = body.filename.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    # Tenant ownership comes from the account context. The old form fields are
    # retained for API compatibility, but a caller cannot move a file into a
    # different company by posting another company_id.
    account_company = await _account_company(session, x_company_id)
    if account_company is None:
        raise HTTPException(status_code=409, detail="This account is not linked to a customer company.")
    company_id = account_company.id
    if body.company_id is not None and body.company_id != company_id:
        raise HTTPException(status_code=403, detail="Uploads belong to the company registered to this account.")

    vehicle = None
    if body.vehicle_id:
        vehicle = await session.get(Vehicle, body.vehicle_id)
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        if company_id is None or vehicle.company_id != company_id:
            raise HTTPException(status_code=403, detail="Vehicle is assigned to another customer.")

    # The filename is the operator-facing identity of a card download. Do not
    # archive or analyse the same named file twice; an operator re-selecting a
    # file should get a clear confirmation rather than another upload result.
    existing = (await session.execute(
        select(TachoFile)
        .where(
            func.lower(TachoFile.filename) == filename.lower(),
            TachoFile.file_kind == body.file_kind,
            TachoFile.parsed.is_(True),
            (TachoFile.company_id == company_id if company_id is not None
             else TachoFile.company_id.is_(None)),
            # Only your own copy counts: another company's upload of the same file stays theirs.
            or_(scope.files(), TachoFile.uploaded_by_user_id == principal.user_id),
        )
        .order_by(TachoFile.created_at.desc())
        .limit(1)
    )).scalars().first()
    if existing is not None:
        infringement_count = (await session.execute(
            select(func.count()).select_from(Infringement).where(
                Infringement.source_file_id == existing.id
            )
        )).scalar_one()
        return {
            "file_id": str(existing.id),
            "filename": existing.filename,
            "sha256": existing.sha256,
            "size_bytes": existing.size_bytes,
            "parsed": True,
            "already_analyzed": True,
            "message": "File already analysed.",
            "driver_ref": existing.driver_ref,
            "infringements_found": infringement_count,
            "infringements_new": 0,
        }

    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    meta = archive.store(filename, data)
    tf = TachoFile(
        filename=filename, file_kind=body.file_kind,
        company_id=company_id, vehicle_id=vehicle.id if vehicle else None,
        driver_ref=body.driver_ref,
        vehicle_ref=vehicle.registration if vehicle else body.vehicle_ref,
        size_bytes=meta["size_bytes"], sha256=meta["sha256"],
        storage_path=meta["storage_path"], source="upload",
        retain_until=meta["retain_until"], uploaded_by_user_id=principal.user_id)
    session.add(tf)
    await session.flush()

    result = {"file_id": str(tf.id), "sha256": meta["sha256"], "size_bytes": meta["size_bytes"],
              "parsed": False, "infringements_found": 0, "infringements_new": 0}

    if body.file_kind == "driver_card":
        try:
            parsed, parser_name = _parse_driver_card(data)
            tf.parsed = True
            # Prefer what the caller said, then the card holder's own name or
            # card number, and only fall back to the file hash when the card
            # carries no identification of its own.
            driver_ref = (body.driver_ref or parsed.get("driver_ref")
                          or f"file:{meta['sha256'][:8]}")[:40]
            tf.driver_ref = driver_ref
            tf.card_number = parsed.get("card_number") or tf.card_number
            tf.card_expiry = parsed.get("card_expiry") or tf.card_expiry
            await _persist_activities(session, parsed, tf.id, company_id,
                                      vehicle.id if vehicle else None, vehicle.registration if vehicle else body.vehicle_ref,
                                      driver_ref)
            found = analyse(parsed["activities"], parsed.get("places"),
                            parsed.get("card_gaps"))
            added = await _persist_infringements(session, driver_ref, found, tf.id, company_id)
            result.update(parsed=True, parser=parser_name, days=parsed["days"], driver_ref=driver_ref,
                          driver_name=parsed.get("driver_name"),
                          card_number=parsed.get("card_number"),
                          infringements_found=len(found), infringements_new=added)
        except Exception as e:
            tf.parsed = False
            tf.parse_error = str(e)[:500]
            result["parse_error"] = str(e)
    elif body.file_kind == "vehicle_unit":
        # The operating company comes off the unit itself, which is the only
        # source that does not depend on how somebody organised their account.
        try:
            tf.company_name = operators.clean_name(
                ddd_parser.parse_vehicle_unit_company(data))
        except Exception:
            tf.company_name = None
        operator = await operators.resolve(session, tf.company_name)
        if operator is not None:
            tf.operator_id = operator.id
            result["operator"] = operator.name
        try:
            # Vehicle-unit files are not driver cards. Parse the VU identity
            # first, then find (or create) the account's vehicle by the
            # registration stored inside the DDD. No vehicle picker is needed.
            parsed = parse_vehicle_unit(data)
            tf.parsed = True
            source_vehicle_ref = parsed.get("vehicle_ref")
            assigned_vehicle_ref = vehicle.registration if vehicle else None
            identity_mismatch = bool(
                assigned_vehicle_ref and source_vehicle_ref and
                not _same_registration(assigned_vehicle_ref, source_vehicle_ref)
            )

            if vehicle is None and source_vehicle_ref and company_id is not None:
                registration = "".join(source_vehicle_ref.upper().split())
                # Vehicle registrations are normalized by the customer API, so
                # an exact tenant-scoped lookup avoids database-specific string
                # functions and keeps the auto-match predictable.
                vehicle = (await session.execute(select(Vehicle).where(
                    Vehicle.company_id == company_id,
                    Vehicle.registration == registration
                ))).scalar_one_or_none()
                if vehicle is None:
                    vehicle = Vehicle(
                        company_id=company_id, registration=registration,
                        vin=parsed.get("vehicle_vin"),
                        tachograph_serial=parsed.get("tachograph_serial"),
                    )
                    session.add(vehicle)
                    await session.flush()
                    result["vehicle_created"] = True

            if vehicle:
                if parsed.get("vehicle_vin") and not vehicle.vin:
                    vehicle.vin = parsed["vehicle_vin"]
                if parsed.get("tachograph_serial") and not vehicle.tachograph_serial:
                    vehicle.tachograph_serial = parsed["tachograph_serial"]
                # The unit says who runs this truck. A disagreement with what
                # is on record is reported, never applied: re-badging a vehicle
                # silently would rewrite whose name is on its past reports.
                outcome = await operators.note_vehicle(vehicle, operator)
                if outcome != "none":
                    result["operator_on_vehicle"] = outcome
                if outcome == "conflict":
                    result["operator_conflict"] = {
                        "vehicle": vehicle.registration,
                        "unit_says": operator.name if operator else None,
                        "on_record": str(vehicle.operator_id),
                    }
            tf.vehicle_id = vehicle.id if vehicle else None
            tf.vehicle_ref = vehicle.registration if vehicle else source_vehicle_ref

            await _persist_activities(
                session, parsed, tf.id, company_id, vehicle.id if vehicle else None,
                tf.vehicle_ref, activity_driver_refs=parsed.get("activity_driver_refs"))
            result.update(
                parsed=True, parser=parsed.get("parser", "tachograph-go"),
                days=parsed["days"], file_kind="vehicle_unit",
                vehicle_id=str(vehicle.id) if vehicle else None,
                vehicle_ref=source_vehicle_ref, vehicle_vin=parsed.get("vehicle_vin"),
                tachograph_serial=parsed.get("tachograph_serial"),
                generation=parsed.get("generation"), drivers=parsed.get("drivers", []),
                activities=len(parsed.get("activities", [])),
                identity_mismatch=identity_mismatch,
            )
        except Exception as e:
            tf.parsed = False
            tf.parse_error = str(e)[:500]
            result["parse_error"] = str(e)
    await session.commit()
    return result


@router.post("/upload-batch")
async def upload_batch(files: list[UploadIn], session: AsyncSession = Depends(get_session),
                       x_company_id: str | None = Header(default=None),
                       principal: Principal = Depends(require_manager),
                       scope: TachoScope = Depends(tacho_scope)) -> dict:
    """Upload several driver-card or VU files and return one result per file.

    A bad file must not hide the result of the other files in the same picker
    operation, so validation failures are returned alongside successful uploads.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    results = []
    for item in files:
        try:
            results.append(await upload(item, session=session, x_company_id=x_company_id,
                                        principal=principal, scope=scope))
        except HTTPException as exc:
            results.append({"filename": item.filename, "parsed": False,
                            "error": exc.detail, "status_code": exc.status_code})
        except Exception as exc:
            results.append({"filename": item.filename, "parsed": False,
                            "error": str(exc)[:500]})
    return {"files": results, "total": len(results),
            "successful": sum(1 for item in results if "error" not in item)}


@router.post("/files/{file_id}/assign")
async def assign_file(file_id: uuid.UUID, company_id: uuid.UUID, vehicle_id: uuid.UUID | None = None,
                      x_company_id: str | None = Header(default=None),
                      session: AsyncSession = Depends(get_session),
                      principal: Principal = Depends(require_manager)) -> dict:
    """Explicitly assign an archived download to a customer and optional vehicle."""
    _super_admin_only(principal)
    if x_company_id:
        try:
            if uuid.UUID(x_company_id) != company_id:
                raise HTTPException(status_code=403, detail="The selected customer does not match the assignment.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="X-Company-ID is not a valid UUID.") from exc
    if await session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    file = await session.get(TachoFile, file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="Tacho file not found.")
    if file.company_id is not None and file.company_id != company_id:
        raise HTTPException(status_code=409, detail="This file belongs to another customer.")
    if vehicle_id:
        vehicle = await session.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        if vehicle.company_id != company_id:
            raise HTTPException(status_code=403, detail="Vehicle is assigned to another customer.")
        file.vehicle_id = vehicle.id
        file.vehicle_ref = vehicle.registration
    file.company_id = company_id
    await session.commit()
    return {"file_id": str(file.id), "company_id": str(company_id),
            "vehicle_id": str(file.vehicle_id) if file.vehicle_id else None,
            "vehicle_ref": file.vehicle_ref, "assigned": True}


@router.post("/reanalyse")
async def reanalyse(body: ReanalyseIn, session: AsyncSession = Depends(get_session),
                    scope: TachoScope = Depends(tacho_scope)) -> dict:
    """Re-run the rules over already-archived driver cards.

    Infringements are derived data, so when the engine is corrected the stored
    rows are stale and have to be rebuilt from the .ddd files. Rows a manager
    has already acknowledged or dismissed are left alone: those record a human
    decision, so they are reported back for review instead of being rewritten.
    """
    stmt = select(TachoFile).where(TachoFile.file_kind == "driver_card", scope.files())
    if body.file_id:
        stmt = stmt.where(TachoFile.id == body.file_id)
    files = (await session.execute(stmt)).scalars().all()

    out = {"files": 0, "removed": 0, "found": 0, "added": 0,
           "kept_actioned": 0, "errors": [], "drivers": []}
    for tf in files:
        try:
            data = archive.read(tf.storage_path)
            parsed, parser_name = _parse_driver_card(data)
        except Exception as e:                       # unreadable / not a card
            tf.parse_error = str(e)[:500]
            out["errors"].append({"file_id": str(tf.id), "filename": tf.filename,
                                  "error": str(e)[:200]})
            continue

        driver_ref = (parsed.get("driver_ref") or tf.driver_ref
                      or f"file:{(tf.sha256 or '')[:8]}")[:40]
        tf.driver_ref = driver_ref
        tf.card_number = parsed.get("card_number") or tf.card_number
        tf.card_expiry = parsed.get("card_expiry") or tf.card_expiry
        tf.parsed = True
        tf.parse_error = None

        actioned = (await session.execute(
            select(func.count()).select_from(Infringement).where(
                Infringement.source_file_id == tf.id,
                Infringement.status != "open"))).scalar_one()
        if body.replace_open:
            reviewed = select(InfringementReview.infringement_id)   # signed or debriefed: keep
            removed = (await session.execute(
                delete(Infringement).where(
                    Infringement.source_file_id == tf.id,
                    Infringement.status == "open",
                    Infringement.id.not_in(reviewed)))).rowcount or 0
            out["removed"] += removed
            await session.flush()

        await _persist_activities(session, parsed, tf.id, tf.company_id, tf.vehicle_id,
                                  tf.vehicle_ref, driver_ref)
        found = analyse(parsed["activities"], parsed.get("places"),
                        parsed.get("card_gaps"))
        added = await _persist_infringements(session, driver_ref, found, tf.id, tf.company_id)
        out["files"] += 1
        out["found"] += len(found)
        out["added"] += added
        out["kept_actioned"] += actioned
        out["drivers"].append({"file_id": str(tf.id), "driver_ref": driver_ref,
                               "parser": parser_name, "days": parsed["days"],
                               "infringements": len(found)})
    await session.commit()
    return out


async def _report_for(session: AsyncSession, file_id: uuid.UUID | None,
                      driver_ref: str | None, start: date | None,
                      end: date | None, scope: TachoScope, hidden_rules: set[str] | None = None) -> dict:
    """Pick the card file the report is about, then build the report from it.
    hidden_rules: infringement types the user has chosen to leave off the report."""
    stmt = select(TachoFile).where(TachoFile.file_kind == "driver_card", scope.files())
    if file_id:
        stmt = stmt.where(TachoFile.id == file_id)
    elif driver_ref:
        stmt = stmt.where(TachoFile.driver_ref == driver_ref)
    files = (await session.execute(
        stmt.order_by(TachoFile.created_at.desc()))).scalars().all()
    if not files:
        raise HTTPException(status_code=404, detail="No driver-card file to report on.")
    if not file_id and not driver_ref and len({f.driver_ref for f in files}) > 1:
        raise HTTPException(
            status_code=400,
            detail="More than one driver is archived; pass driver_ref or file_id.")
    tf = files[0]

    try:
        parsed, _parser_name = _parse_driver_card(archive.read(tf.storage_path))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read the card file: {e}")

    # Prefer the infringements on record, so anything a manager has already
    # dismissed stays off the driver's report; fall back to analysing the file
    # when it has never been run through the engine.
    rows = (await session.execute(select(Infringement).where(
        Infringement.source_file_id == tf.id,
        Infringement.status != "dismissed"))).scalars().all()
    if rows:
        found = [RuleInfringement(
            rule=r.rule, title=r.title, severity=r.severity,
            start=r.period_start, end=r.period_end, detail=r.detail or "",
            limit_minutes=r.limit_minutes, actual_minutes=r.actual_minutes)
            for r in rows]
    else:
        found = analyse(parsed["activities"], parsed.get("places"),
                        parsed.get("card_gaps"))
    if hidden_rules:
        found = [i for i in found if i.rule not in hidden_rules]
    reviews = await infringement_reviews.reviews_for(session, [r.id for r in rows])
    signoff = {(r.rule, r.period_start.isoformat()): infringement_reviews.view(reviews.get(r.id)) for r in rows}

    operator = await _operator_for_report(session, parsed, start, end)
    # A card lists every lorry the driver has ever been in, including other
    # operators'. An account sees its own and no more: those registrations and
    # the mileage done in them are not theirs to read. An administrator, who
    # has no one account, keeps the full list.
    report = tacho_report.build_report(
        parsed, found, start=start, end=end,
        driver_ref=tf.driver_ref or parsed.get("driver_ref"),
        company_name=operator["name"],
        only_regs=None if scope.everything else scope.regs)
    # Carried on the report so the screen and the emailing step can see it: a
    # report spanning two operators must not be sent to either as though it
    # were theirs.
    report["operator"] = operator
    for week in report.get("weeks", []):
        for item in week.get("infringements", []) + week.get("working_time_infringements", []):
            item["review"] = signoff.get((item["rule"], item.get("start")))
    return report


@router.get("/timeline")
async def timeline(driver_ref: str | None = None,
                   start: datetime | None = None, end: datetime | None = None,
                   company_id: uuid.UUID | None = None,
                   session: AsyncSession = Depends(get_session),
                   scope: TachoScope = Depends(tacho_scope)) -> list[dict]:
    """Return driver-card activities for the driver timeline.

    Vehicle-unit activities are deliberately excluded. Registrations come from
    the vehicle spells recorded on the driver's card for each activity day.
    """
    return await timeline_rows(session, scope, driver_ref, start, end, company_id)


async def timeline_rows(session: AsyncSession, scope: TachoScope, driver_ref: str | None = None,
                        start: datetime | None = None, end: datetime | None = None,
                        company_id: uuid.UUID | None = None) -> list[dict]:
    stmt = (select(TachoActivity)
            .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
            .where(TachoFile.file_kind == "driver_card", scope.activities())
            .order_by(TachoActivity.started_at))
    if company_id:
        stmt = stmt.where(TachoActivity.company_id == company_id)
    if driver_ref:
        stmt = stmt.where(TachoActivity.driver_ref == driver_ref)
    if start:
        stmt = stmt.where(TachoActivity.ended_at >= _aware(start))
    if end:
        stmt = stmt.where(TachoActivity.started_at <= _aware(end))
    rows = (await session.execute(stmt.limit(10000))).scalars().all()
    return [{"id": str(a.id), "company_id": str(a.company_id) if a.company_id else None,
             "source_file_id": str(a.source_file_id), "driver_ref": a.driver_ref,
             "vehicle_id": str(a.vehicle_id) if a.vehicle_id else None,
             "vehicle_ref": a.vehicle_ref, "activity": a.activity_type.upper(),
             "start": a.started_at.isoformat(), "end": a.ended_at.isoformat(),
             "source": a.source, "confidence": a.confidence}
            for a in rows]


@router.get("/timeline.pdf")
async def timeline_pdf(driver_ref: str | None = None,
                       start: datetime | None = None, end: datetime | None = None,
                       company_id: uuid.UUID | None = None,
                       session: AsyncSession = Depends(get_session),
                       scope: TachoScope = Depends(tacho_scope)) -> Response:
    """Export driver-card activities as daily 24-hour tachograph charts."""
    return await timeline_pdf_response(session, scope, driver_ref, start, end, company_id)


async def timeline_pdf_response(session: AsyncSession, scope: TachoScope, driver_ref: str | None = None,
                                start: datetime | None = None, end: datetime | None = None,
                                company_id: uuid.UUID | None = None) -> Response:
    rows = await timeline_rows(session, scope, driver_ref, start, end, company_id)
    safe = "".join(c if c.isalnum() else "_"
                   for c in (driver_ref or "timeline")).strip("_") or "timeline"
    return Response(
        content=tacho_pdf.render_timeline(rows, driver_ref=driver_ref),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}_timeline.pdf"'})


@router.get("/report")
async def report(file_id: uuid.UUID | None = None, driver_ref: str | None = None,
                 start: date | None = None, end: date | None = None,
                 session: AsyncSession = Depends(get_session),
                 scope: TachoScope = Depends(tacho_scope),
                 principal: Principal = Depends(require_manager)) -> dict:
    hidden, _ = await report_settings.hidden_for(session, principal.user_id)
    return await _report_for(session, file_id, driver_ref, start, end, scope, hidden)


@router.get("/report.pdf")
async def report_pdf(file_id: uuid.UUID | None = None, driver_ref: str | None = None,
                     start: date | None = None, end: date | None = None,
                     session: AsyncSession = Depends(get_session),
                     scope: TachoScope = Depends(tacho_scope),
                     principal: Principal = Depends(require_manager)) -> Response:
    hidden, _ = await report_settings.hidden_for(session, principal.user_id)
    data = await _report_for(session, file_id, driver_ref, start, end, scope, hidden)
    who = (data["driver"].get("name") or data["driver"].get("ref") or "driver")
    safe = "".join(c if c.isalnum() else "_" for c in who).strip("_") or "driver"
    name = f"{safe}_{data['period']['from']}_{data['period']['to']}.pdf"
    return Response(
        content=tacho_pdf.render(data), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/report/send")
async def send_report(body: dict = Body(default={}),
                      session: AsyncSession = Depends(get_session),
                      scope: TachoScope = Depends(tacho_scope),
                      principal: Principal = Depends(require_manager)) -> dict:
    """Email driver reports now, instead of waiting for Monday morning.

    What is sent is what the Hours page is showing. Dates given here are
    honoured; with the date boxes left empty and a driver named, the whole of
    that driver's card goes - the same span the page draws and the Download PDF
    button saves. Defaulting to last week instead would email one page where
    the screen showed a year, which is exactly the wrong surprise.

    With no `driver_ref` at all it falls back to the week, which is the Monday
    job's job: every driver who worked, in one email.

    It goes to the address the account is registered with unless another is
    given here.
    """
    if not mailer.configured():
        raise HTTPException(status_code=400,
                            detail="No mail server is set up, so nothing can be emailed.")

    today = date.today()
    start = date.fromisoformat(body["start"]) if body.get("start") else None
    end = date.fromisoformat(body["end"]) if body.get("end") else None
    whole_card = start is None and end is None and bool(body.get("driver_ref"))
    if not whole_card and (start is None or end is None):
        start, end = driver_reports.last_full_week(today)

    to = (body.get("to") or principal.email or "").strip()
    name = principal.name or principal.email or "your account"
    week = driver_reports.AccountWeek(user_id=principal.user_id or 0, account=name,
                                      email=to or None)

    hidden, _ = await report_settings.hidden_for(session, principal.user_id)
    wanted = ([body["driver_ref"]] if body.get("driver_ref")
              else await driver_reports.drivers_active(session, scope, start, end))
    for driver_ref in wanted:
        week.reports.append(
            await driver_reports.build_week(session, scope, driver_ref, start, end, hidden))

    if not week.reports:
        covers = (f"between {start} and {end}" if start and end else "on that card")
        raise HTTPException(status_code=400,
                            detail=f"No driver worked {covers}, so there is nothing to send.")
    if not any(report.pdf for report in week.reports):
        why = next((r.problem for r in week.reports if r.problem), "the report could not be built")
        raise HTTPException(status_code=422, detail=f"Nothing could be attached: {why}")

    # Asked for the whole card, the span is only known once it is built, so the
    # covering note and the subject take it from the reports themselves.
    if start is None or end is None:
        froms = [r.period_from for r in week.reports if r.period_from]
        tos = [r.period_to for r in week.reports if r.period_to]
        start = min(froms) if froms else driver_reports.last_full_week(today)[0]
        end = max(tos) if tos else driver_reports.last_full_week(today)[1]

    try:
        sent_to = await driver_reports.send_week(session, week, start, end,
                                                 to=to or None, automatic=False)
    except mailer.MailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"sent_to": sent_to, "drivers": len(week.reports),
            "attached": len(driver_reports.attachments(week)),
            "infringements": week.total_infringements,
            "weeks": sum(r.weeks for r in week.reports),
            "period": {"start": start.isoformat(), "end": end.isoformat()}}


async def _card_spans(session: AsyncSession, scope: TachoScope, since: datetime,
                      driver_ref: str | None = None) -> dict[str, list]:
    """Driver-card activity per card holder (your drivers only)."""
    stmt = (select(TachoActivity.driver_ref, TachoActivity.activity_type, TachoActivity.started_at, TachoActivity.ended_at)
            .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
            .where(TachoFile.file_kind == "driver_card", scope.activities(), TachoActivity.ended_at >= since))
    if driver_ref:
        stmt = stmt.where(TachoActivity.driver_ref == driver_ref)
    out: dict[str, list] = {}
    for ref, kind, start, end in (await session.execute(stmt)).all():
        if ref:
            out.setdefault(ref, []).append((kind, start, end))
    return out


@router.get("/calendar")
async def calendar(weeks: int = 2, end: date | None = None, driver_ref: str | None = None,
                   reference_weeks: int = 17,
                   session: AsyncSession = Depends(get_session),
                   scope: TachoScope = Depends(tacho_scope)) -> dict:
    """Every driver's fortnight on one grid: who worked, who rested, who is missing.

    The whole depot at once, which is the question actually asked first thing in
    the morning. One row per driver, one cell per day, plus how much working
    time each has left this week and next.
    """
    if weeks not in (1, 2, 4, 6):
        raise HTTPException(status_code=400, detail="Show 1, 2, 4 or 6 weeks.")
    if reference_weeks not in (17, 26):
        raise HTTPException(status_code=400, detail="The reference period is 17 or 26 weeks.")

    today = datetime.now(wtd_service.LONDON).date()
    first, last = driver_calendar.span(end or today, weeks)

    # The average needs history well before the grid starts, so the card data
    # is fetched from far enough back for the reference period to be real.
    since_day = driver_calendar.week_start(first) - timedelta(weeks=reference_weeks)
    since = datetime.combine(since_day, datetime.min.time(), timezone.utc)
    spans = await _card_spans(session, scope, since, driver_ref)

    # Infringements land on the day they start, in local time, so a breach that
    # begins at 23:00 marks the day the driver would say it happened.
    found: dict[str, dict[date, list]] = {}
    rows = (await session.execute(
        select(Infringement.driver_ref, Infringement.period_start, Infringement.severity)
        .where(Infringement.status != "dismissed", scope.infringements(),
               Infringement.period_start >= datetime.combine(first, datetime.min.time(), timezone.utc)))).all()
    for ref, when, severity in rows:
        day = when.astimezone(wtd_service.LONDON).date()
        found.setdefault(ref, {}).setdefault(day, []).append(severity or "serious")

    # When each card was last downloaded - the number the office chases.
    downloads: dict[str, datetime] = {}
    for ref, when in (await session.execute(
            select(TachoFile.driver_ref, func.max(TachoFile.created_at))
            .where(TachoFile.file_kind == "driver_card", TachoFile.driver_ref.isnot(None),
                   scope.files()).group_by(TachoFile.driver_ref))).all():
        downloads[ref] = when

    names = {d.get("uniqueId"): d.get("name") for d in (scope.drivers or [])}
    drivers = [
        driver_calendar.build(
            ref, names.get(ref), items, found.get(ref, {}), first, last, today,
            last_download=downloads.get(ref), reference_weeks=reference_weeks)
        for ref, items in sorted(spans.items())
    ]
    # The drivers needing attention first: missing records, then infringements.
    drivers.sort(key=lambda d: (-d["days_without_a_record"], -d["infringements"], d["name"].lower()))

    return {
        "from": first.isoformat(), "to": last.isoformat(), "weeks": weeks,
        "today": today.isoformat(), "reference_weeks": reference_weeks,
        "drivers": drivers,
        "totals": {
            "drivers": len(drivers),
            "without_a_record": sum(1 for d in drivers if d["days_without_a_record"]),
            "infringements": sum(d["infringements"] for d in drivers),
            "worked_days": sum(d["worked_days"] for d in drivers),
        },
    }


@router.get("/wtd")
async def working_time(weeks: int = 26, reference_weeks: int = 17, driver_ref: str | None = None,
                       session: AsyncSession = Depends(get_session), scope: TachoScope = Depends(tacho_scope)) -> dict:
    """Road Transport Working Time: weekly totals, rolling average, 60h weeks and night work, per driver."""
    from app.services import wtd

    if weeks < 1 or weeks > 104 or reference_weeks not in (17, 26):
        raise HTTPException(status_code=400, detail="Choose 1-104 weeks and a 17 or 26 week reference period.")
    today = datetime.now(wtd.LONDON).date()
    since_day = wtd.week_start(today) - timedelta(weeks=weeks + reference_weeks)
    since = datetime.combine(since_day, datetime.min.time(), timezone.utc)
    spans = await _card_spans(session, scope, since, driver_ref)
    breaks = (await session.execute(
        select(Infringement.driver_ref, Infringement.period_start).where(
            Infringement.rule.in_(("wtd_break", "wtd_daily_break")), Infringement.status != "dismissed",
            scope.infringements(), Infringement.period_start >= since)
    )).all()
    drivers = []
    for ref, items in sorted(spans.items()):
        rep = wtd.report(items, weeks=weeks, reference_weeks=reference_weeks, today=today)
        per_week: dict[str, int] = {}
        for bref, when in breaks:
            if bref == ref:
                key = wtd.week_start(when.astimezone(wtd.LONDON).date()).isoformat()
                per_week[key] = per_week.get(key, 0) + 1
        for w in rep["weeks"]:
            w["break_infringements"] = per_week.get(w["week_start"], 0)
        drivers.append({"driver_ref": ref, **rep})
    return {"weeks": weeks, "reference_weeks": reference_weeks, "drivers": drivers,
            "limits": {"week_minutes": wtd.WEEK_LIMIT, "average_minutes": wtd.AVERAGE_LIMIT, "night_minutes": wtd.NIGHT_LIMIT}}


@router.get("/hours.csv")
async def hours_csv(start: date, end: date, session: AsyncSession = Depends(get_session),
                    scope: TachoScope = Depends(tacho_scope)) -> Response:
    """Daily hours per driver from card data, with app shift times, for payroll and working time records."""
    import csv
    import io

    from app.models.driver_auth import DriverAccount, DriverMembership
    from app.models.shifts import Shift
    from app.services import wtd
    from app.services.tacho_scope import card_key

    if end < start or (end - start).days > 400:
        raise HTTPException(status_code=400, detail="Choose a date range of up to 400 days.")
    since = datetime.combine(start - timedelta(days=1), datetime.min.time(), timezone.utc)
    spans = await _card_spans(session, scope, since)
    until = datetime.combine(end + timedelta(days=2), datetime.min.time(), timezone.utc)

    # App shifts, matched to the card holder through the driver login's card number.
    ref_cards = dict((await session.execute(
        select(TachoFile.driver_ref, TachoFile.card_number).where(
            TachoFile.file_kind == "driver_card", scope.files(), TachoFile.card_number.is_not(None)))).all())
    accounts = {card_key(a.unique_id): a for a in (await session.execute(select(DriverAccount))).scalars().all()
                if len(card_key(a.unique_id)) == 14}
    memberships = (await session.execute(select(DriverMembership.account_id, DriverMembership.traccar_driver_id))).all()
    shifts_by_day: dict[tuple[str, str], list] = {}
    for ref, number in ref_cards.items():
        account = accounts.get(card_key(number))
        if not account:
            continue
        ids = [tid for aid, tid in memberships if aid == account.id]
        rows = (await session.execute(select(Shift).where(
            Shift.clocked_in_at >= since, Shift.clocked_in_at < until,
            (Shift.traccar_driver_id.in_(ids) if ids else Shift.driver_name == account.name)))).scalars().all()
        for sh in rows:
            day = sh.clocked_in_at.astimezone(wtd.LONDON).date().isoformat()
            shifts_by_day.setdefault((ref, day), []).append(sh)

    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["Driver", "Date", "First activity", "Last activity", "Driving (h:mm)", "Other work (h:mm)",
                  "Availability (h:mm)", "Working time (h:mm)", "Night work", "App shift start", "App shift end",
                  "App shift length (h:mm)", "Vehicle"])
    hm = lambda m: f"{m // 60}:{m % 60:02d}"  # noqa: E731
    for ref in sorted(spans):
        for row in wtd.daily_rows(spans[ref], start, end):
            shifts = shifts_by_day.get((ref, row["date"]), [])
            first = min(shifts, key=lambda x: x.clocked_in_at) if shifts else None
            ends = [x.clocked_out_at for x in shifts if x.clocked_out_at]
            last_end = max(ends) if ends else None
            length = int((last_end - first.clocked_in_at).total_seconds() // 60) if first and last_end else None
            out.writerow([ref, row["date"], row["first_activity"], row["last_activity"], hm(row["drive_minutes"]),
                          hm(row["other_work_minutes"]), hm(row["poa_minutes"]), hm(row["working_minutes"]),
                          "yes" if row["night_work"] else "",
                          first.clocked_in_at.astimezone(wtd.LONDON).strftime("%H:%M") if first else "",
                          last_end.astimezone(wtd.LONDON).strftime("%H:%M") if last_end else "",
                          hm(length) if length is not None else "",
                          ", ".join(sorted({x.vehicle_reg for x in shifts if x.vehicle_reg}))])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="driver-hours-{start}-to-{end}.csv"'})


@router.get("/operators")
async def list_operators(session: AsyncSession = Depends(get_session),
                         scope: TachoScope = Depends(tacho_scope),
                         principal: Principal = Depends(require_manager)) -> dict:
    """The operating companies read off the vehicle units, and their vehicles.

    This is what decides whose name goes on a driver's report, so it is worth
    somebody's eyes: a customer running several legal entities out of one login
    should see each one here, with the right trucks under it.
    """
    rows = (await session.execute(
        select(Operator, func.count(Vehicle.id))
        .outerjoin(Vehicle, Vehicle.operator_id == Operator.id)
        .group_by(Operator.id).order_by(Operator.name))).all()

    vehicles = (await session.execute(
        select(Vehicle.registration, Vehicle.operator_id, Operator.name)
        .outerjoin(Operator, Operator.id == Vehicle.operator_id)
        .order_by(Vehicle.registration))).all()

    return {
        "operators": [{
            "id": str(op.id), "name": op.name, "source": op.source,
            "contact_email": op.contact_email, "vehicles": count,
        } for op, count in rows],
        "vehicles": [{"registration": reg, "operator": name,
                      "operator_id": str(oid) if oid else None}
                     for reg, oid, name in vehicles],
        # Vehicles with no operator yet: nothing has been downloaded from their
        # unit, so nobody knows whose name belongs on their driver's report.
        "unassigned": [reg for reg, oid, _ in vehicles if oid is None],
    }


@router.put("/vehicles/{registration}/operator")
async def set_vehicle_operator(registration: str, body: dict = Body(...),
                               session: AsyncSession = Depends(get_session),
                               principal: Principal = Depends(require_manager)) -> dict:
    """Say which company operates a vehicle, by hand.

    Needed in two cases: a truck whose unit has never been downloaded, and one
    the download got wrong or that has changed hands. Set deliberately here
    rather than by a download quietly overwriting what is on record.
    """
    _super_admin_only(principal)
    reg = "".join(str(registration).upper().split())
    vehicle = (await session.execute(
        select(Vehicle).where(Vehicle.registration == reg))).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=404, detail=f"No vehicle {reg} on the compliance side yet.")

    name = (body.get("operator") or "").strip()
    if not name:
        vehicle.operator_id = None
        await session.commit()
        return {"registration": reg, "operator": None}

    operator = await operators.resolve(session, name, source="manual")
    if operator is None:
        raise HTTPException(status_code=400, detail="That is not a usable company name.")
    vehicle.operator_id = operator.id
    await session.commit()
    logger_name = principal.email or principal.name
    import logging
    logging.getLogger("tacho.operators").info(
        "%s set %s to operator %s", logger_name, reg, operator.name)
    return {"registration": reg, "operator": operator.name, "id": str(operator.id)}


@router.get("/report-settings")
async def get_report_settings(session: AsyncSession = Depends(get_session),
                              scope: TachoScope = Depends(tacho_scope),
                              principal: Principal = Depends(require_manager)) -> dict:
    """Infringement types on the weekly report, with how often each occurs in your data."""
    hidden, source = await report_settings.hidden_for(session, principal.user_id)
    default_hidden, _ = await report_settings.hidden_for(session, None)
    counts = dict((await session.execute(
        select(Infringement.rule, func.count()).where(scope.infringements()).group_by(Infringement.rule))).all())
    return {
        "source": source,
        "can_set_default": modules.is_super_admin(principal),
        "rules": [{"code": code, "title": title, "group": group, "shown": code not in hidden,
                   "shown_by_default": code not in default_hidden, "count": counts.get(code, 0)}
                  for code, title, group in report_settings.RULES],
    }


@router.put("/report-settings")
async def put_report_settings(body: ReportSettingsIn, session: AsyncSession = Depends(get_session),
                              principal: Principal = Depends(require_manager)) -> dict:
    unknown = set(body.hidden) - report_settings.CODES
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown infringement type: {', '.join(sorted(unknown))}")
    if body.for_everyone:
        _super_admin_only(principal)
        hidden = await report_settings.save(session, report_settings.DEFAULT_KEY, body.hidden, principal.name)
    else:
        if principal.user_id is None:
            raise HTTPException(status_code=400, detail="Your account can't store report settings.")
        hidden = await report_settings.save(session, report_settings.user_key(principal.user_id), body.hidden, principal.name)
    return {"hidden": hidden, "for_everyone": body.for_everyone}


@router.delete("/report-settings")
async def reset_report_settings(session: AsyncSession = Depends(get_session),
                                principal: Principal = Depends(require_manager)) -> dict:
    """Go back to the default choice."""
    if principal.user_id is not None:
        await report_settings.clear(session, report_settings.user_key(principal.user_id))
    hidden, source = await report_settings.hidden_for(session, principal.user_id)
    return {"hidden": sorted(hidden), "source": source}


@router.get("/infringements")
async def list_infringements(status: str = "open", driver_ref: str | None = None,
                             vehicle_ref: str | None = None,
                             session: AsyncSession = Depends(get_session),
                             scope: TachoScope = Depends(tacho_scope)) -> list[dict]:
    stmt = select(Infringement, TachoFile.vehicle_ref).outerjoin(
        TachoFile, Infringement.source_file_id == TachoFile.id
    ).where(scope.infringements()).order_by(Infringement.period_start.desc())
    if status != "all":
        stmt = stmt.where(Infringement.status == status)
    if driver_ref:
        stmt = stmt.where(Infringement.driver_ref == driver_ref)
    if vehicle_ref:
        stmt = stmt.where(TachoFile.vehicle_ref == vehicle_ref)
    rows = (await session.execute(stmt.limit(1000))).all()
    reviews = await infringement_reviews.reviews_for(session, [r.id for r, _ in rows])
    return [{
        "id": str(r.id), "driver_ref": r.driver_ref, "vehicle_ref": vehicle,
        "rule": r.rule, "code": tacho_rules_codes(r.rule), "title": r.title,
        "severity": r.severity, "status": r.status,
        "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
        "detail": r.detail, "limit_minutes": r.limit_minutes, "actual_minutes": r.actual_minutes,
        "review": infringement_reviews.view(reviews.get(r.id)),
    } for r, vehicle in rows]


@router.get("/debrief-actions")
async def debrief_actions() -> list[dict]:
    return [{"code": code, "label": label} for code, label in infringement_reviews.ACTIONS.items()]


async def _visible_infringement(session: AsyncSession, scope: TachoScope, inf_id: uuid.UUID) -> Infringement:
    inf = await session.get(Infringement, inf_id)
    if inf is None or not scope.allows_infringement(inf):
        raise HTTPException(status_code=404, detail="Infringement not found.")
    return inf


@router.post("/infringements/{inf_id}/debrief")
async def debrief(inf_id: uuid.UUID, body: DebriefIn, session: AsyncSession = Depends(get_session),
                  scope: TachoScope = Depends(tacho_scope), principal: Principal = Depends(require_manager)) -> dict:
    """Record what the office did about an infringement (the driver's debrief)."""
    if body.action not in infringement_reviews.ACTIONS:
        raise HTTPException(status_code=400, detail="Choose what was done about this infringement.")
    inf = await _visible_infringement(session, scope, inf_id)
    review = (await infringement_reviews.reviews_for(session, [inf.id])).get(inf.id)
    if review is None:
        review = InfringementReview(infringement_id=inf.id)
        session.add(review)
    review.debriefed_at = datetime.now(timezone.utc)
    review.debriefed_by = principal.name
    review.debrief_action = body.action
    review.debrief_notes = (body.notes or "").strip() or None
    review.updated_at = review.debriefed_at
    if inf.status == "open":
        inf.status = "acknowledged"
    await session.commit()
    return {"id": str(inf.id), "status": inf.status, "review": infringement_reviews.view(review)}


@router.get("/infringements/{inf_id}/signature")
async def infringement_signature(inf_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                                 scope: TachoScope = Depends(tacho_scope)) -> Response:
    inf = await _visible_infringement(session, scope, inf_id)
    review = (await infringement_reviews.reviews_for(session, [inf.id])).get(inf.id)
    if review is None or not review.driver_signature_path:
        raise HTTPException(status_code=404, detail="Not signed yet.")
    return Response(content=media_store.read(review.driver_signature_path), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.post("/infringements/{inf_id}/status")
async def set_status(inf_id: uuid.UUID, body: StatusIn,
                     session: AsyncSession = Depends(get_session),
                     scope: TachoScope = Depends(tacho_scope)) -> dict:
    inf = (await session.execute(
        select(Infringement).where(Infringement.id == inf_id))).scalar_one_or_none()
    if inf is None or not scope.allows_infringement(inf):
        raise HTTPException(status_code=404, detail="Infringement not found.")
    inf.status = body.status
    await session.commit()
    return {"id": str(inf.id), "status": inf.status}


@router.get("/files")
async def list_files(session: AsyncSession = Depends(get_session),
                     scope: TachoScope = Depends(tacho_scope)) -> list[dict]:
    rows = (await session.execute(
        select(TachoFile).where(scope.files()).order_by(TachoFile.created_at.desc()).limit(500))).scalars().all()
    return [{
        "id": str(f.id), "filename": f.filename, "file_kind": f.file_kind,
        "driver_ref": f.driver_ref, "vehicle_ref": f.vehicle_ref,
        "company_name": f.company_name,
        "operator_id": str(f.operator_id) if f.operator_id else None,
        "size_bytes": f.size_bytes, "sha256": f.sha256, "parsed": f.parsed,
        "parse_error": f.parse_error,
        "retain_until": f.retain_until.isoformat() if f.retain_until else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in rows]


@router.get("/downloads")
async def list_downloads(
    limit: int = 200,
    offset: int = 0,
    vehicle_ref: str | None = None,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
    scope: TachoScope = Depends(tacho_scope),
    _license: None = Depends(require_license),
    _module: None = Depends(require_module("tacho")),
) -> dict:
    """Every raw download held, newest first.

    The record of what the fleet actually downloaded, as opposed to what was
    read out of it: a file that would not parse is still the operator's
    evidence and still has to be producible for DVSA, so it is listed here with
    the reason it could not be read rather than hidden.

    This is a separate path from `/files` deliberately: `/files` answers with a
    plain list for the pages that total it up, and two handlers on one path
    means only the first one registered is ever reached.
    """
    # Scoped like every other tachograph listing. These files carry named
    # drivers' hours, so one customer's manager must never see another's.
    query = select(TachoFile).where(scope.files()).order_by(TachoFile.created_at.desc())
    if vehicle_ref:
        query = query.where(TachoFile.vehicle_ref == vehicle_ref.upper().replace(" ", ""))
    if kind in ("driver_card", "vehicle_unit"):
        query = query.where(TachoFile.file_kind == kind)

    total = (await session.execute(
        select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await session.execute(query.limit(min(limit, 500)).offset(offset))).scalars().all()

    return {
        "total": total,
        "files": [{
            "id": str(f.id),
            "filename": f.filename,
            "kind": f.file_kind,
            "vehicle": f.vehicle_ref,
            "driver": f.driver_ref,
            "card_number": f.card_number,
            "company": f.company_name,
            "size_bytes": f.size_bytes,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "retain_until": f.retain_until.isoformat() if f.retain_until else None,
            "parsed": f.parsed,
            "parse_error": f.parse_error,
            "source": f.source,
        } for f in rows],
    }


@router.post("/downloads/reparse")
async def reparse_downloads(
    principal: Principal = Depends(require_manager),
    scope: TachoScope = Depends(tacho_scope),
    _license: None = Depends(require_license),
    _module: None = Depends(require_module("tacho")),
) -> dict:
    """Read the files that would not parse again, with today's parsers.

    Kept deliberately manual. A parser upgrade is the reason to run this, and
    whoever performed the upgrade is the person who should see what changed.
    """
    if not scope.everything:
        raise HTTPException(
            status_code=403,
            detail="Re-reading the archive is an administrator's job.")

    from app.services.download_ingest import reparse

    outcome = await reparse(only_failed=True)
    return {
        "looked_at": len(outcome),
        "now_parse": sum(1 for entry in outcome if entry.get("parsed")),
        "files": [{
            "filename": entry.get("filename"),
            "parsed": entry.get("parsed", False),
            "was": (entry.get("was") or "")[:160] or None,
            "error": entry.get("parse_error") or entry.get("error"),
        } for entry in outcome],
    }


@router.get("/files/{file_id}/raw")
async def raw_file(
    file_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    scope: TachoScope = Depends(tacho_scope),
    _license: None = Depends(require_license),
    _module: None = Depends(require_module("tacho")),
) -> Response:
    """The original download, byte for byte.

    Served exactly as it arrived - no re-encoding, no re-wrapping - because a
    .ddd is a signed file and anything that touches the bytes destroys the
    signature an analysis bureau or DVSA would check it by.
    """
    # Fetched through the caller's own scope rather than by id alone: a file id
    # is not a permission, and these files name drivers.
    record = (await session.execute(select(TachoFile).where(
        TachoFile.id == file_id, scope.files()))).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="That download is not in the archive.")
    try:
        data = archive.read(record.storage_path)
    except OSError as exc:
        raise HTTPException(
            status_code=410,
            detail="The file is on record but its copy is no longer on disk.") from exc
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{record.filename}"',
        "Content-Length": str(len(data)),
        "Cache-Control": "private, max-age=3600",
    })
