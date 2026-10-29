"""Driver compliance records API (licence + office user + "driver_records" module).

GET    /api/driver-records/drivers               every driver with expiry / check status
GET    /api/driver-records/drivers/{id}           one driver's record and Driver CPC courses
PUT    /api/driver-records/drivers/{id}           update the record
POST   /api/driver-records/drivers/{id}/courses   add a Driver CPC course (optional certificate)
DELETE /api/driver-records/courses/{id}
GET    /api/driver-records/courses/{id}/certificate
GET    /api/driver-records/summary               counts for the compliance hub
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.api.maintenance import add_interval
from app.database import get_session
from app.models.driver_records import DriverCpcCourse, DriverRecord
from app.models.tacho import TachoFile
from app.services import auth, media_store
from app.services.auth import Principal
from app.services.tacho_scope import card_key

router = APIRouter(prefix="/api/driver-records", tags=["driver records"],
                   dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("driver_records"))])

EXPIRY_SOON_DAYS = 60
CHECK_SOON_DAYS = 14
DEFAULT_CHECK_MONTHS = 6
CPC_HOURS_REQUIRED = 35
STATUS_ORDER = {"expired": 0, "overdue": 0, "due_soon": 1, "missing": 2, "ok": 3}


class RecordIn(BaseModel):
    licence_number: str | None = Field(default=None, max_length=24)
    licence_categories: str | None = Field(default=None, max_length=80)
    licence_expiry: date | None = None
    licence_checked_on: date | None = None
    licence_points: int | None = Field(default=None, ge=0, le=36)
    licence_check_months: int | None = Field(default=None, ge=1, le=24)
    dqc_expiry: date | None = None
    card_expiry: date | None = None
    medical_expiry: date | None = None
    adr_expiry: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class CourseIn(BaseModel):
    course_date: date
    hours: float = Field(gt=0, le=35)
    title: str = Field(min_length=1, max_length=160)
    provider: str | None = Field(default=None, max_length=160)
    certificate: str | None = None
    certificate_name: str | None = Field(default=None, max_length=200)


def _expiry(label: str, when: date | None, today: date, required: bool = True, source: str | None = None) -> dict:
    if when is None:
        return {"label": label, "date": None, "status": "missing" if required else "not_applicable", "days_left": None, "source": source}
    days = (when - today).days
    status = "expired" if days < 0 else "due_soon" if days <= EXPIRY_SOON_DAYS else "ok"
    return {"label": label, "date": when.isoformat(), "status": status, "days_left": days, "source": source}


def _cpc(courses: list[DriverCpcCourse], dqc_expiry: date | None, today: date) -> dict:
    end = dqc_expiry or today
    start = end - timedelta(days=5 * 365 + 1)
    hours = float(sum(float(c.hours) for c in courses if start < c.course_date <= end))
    if hours >= CPC_HOURS_REQUIRED:
        status = "ok"
    elif dqc_expiry and (dqc_expiry - today).days <= 365:
        status = "due_soon" if dqc_expiry >= today else "expired"
    else:
        status = "missing" if not courses else "ok"
    return {"label": "Driver CPC training", "hours": round(hours, 1), "required": CPC_HOURS_REQUIRED,
            "window_start": start.isoformat(), "window_end": end.isoformat(), "status": status}


def _check(record: DriverRecord | None, today: date) -> dict:
    months = (record.licence_check_months if record and record.licence_check_months else DEFAULT_CHECK_MONTHS)
    last = record.licence_checked_on if record else None
    if last is None:
        return {"label": "Licence check", "last": None, "next_due": None, "every_months": months, "status": "missing", "days_left": None}
    due = add_interval(last, months, "months")
    days = (due - today).days
    status = "overdue" if days < 0 else "due_soon" if days <= CHECK_SOON_DAYS else "ok"
    return {"label": "Licence check", "last": last.isoformat(), "next_due": due.isoformat(), "every_months": months,
            "status": status, "days_left": days, "points": record.licence_points if record else None}


async def _card_expiries(session: AsyncSession) -> dict[str, date]:
    rows = (await session.execute(
        select(TachoFile.card_number, TachoFile.card_expiry).where(
            TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None), TachoFile.card_expiry.is_not(None))
    )).all()
    out: dict[str, date] = {}
    for number, expiry in rows:
        key = card_key(number)
        if key not in out or expiry > out[key]:
            out[key] = expiry
    return out


def _view(driver: dict, record: DriverRecord | None, courses: list[DriverCpcCourse], card_from_downloads: dict[str, date],
          today: date) -> dict:
    key = card_key(driver.get("uniqueId"))
    downloaded = card_from_downloads.get(key) if len(key) == 14 else None
    card_date = (record.card_expiry if record and record.card_expiry else downloaded)
    card_source = "entered" if record and record.card_expiry else ("driver card download" if downloaded else None)
    items = {
        "licence": _expiry("Driving licence", record.licence_expiry if record else None, today),
        "licence_check": _check(record, today),
        "dqc": _expiry("Driver CPC card (DQC)", record.dqc_expiry if record else None, today),
        "cpc_training": _cpc(courses, record.dqc_expiry if record else None, today),
        "tacho_card": _expiry("Tachograph card", card_date, today, source=card_source),
        "medical": _expiry("Medical (D4)", record.medical_expiry if record else None, today, required=False),
        "adr": _expiry("ADR certificate", record.adr_expiry if record else None, today, required=False),
    }
    worst = min((i["status"] for i in items.values() if i["status"] != "not_applicable"),
                key=lambda s: STATUS_ORDER.get(s, 9), default="ok")
    return {
        "traccar_driver_id": int(driver["id"]), "name": driver.get("name"), "identifier": driver.get("uniqueId"),
        "status": worst, "items": items,
        "record": None if record is None else {
            "licence_number": record.licence_number, "licence_categories": record.licence_categories,
            "licence_expiry": record.licence_expiry.isoformat() if record.licence_expiry else None,
            "licence_checked_on": record.licence_checked_on.isoformat() if record.licence_checked_on else None,
            "licence_points": record.licence_points, "licence_check_months": record.licence_check_months,
            "dqc_expiry": record.dqc_expiry.isoformat() if record.dqc_expiry else None,
            "card_expiry": record.card_expiry.isoformat() if record.card_expiry else None,
            "medical_expiry": record.medical_expiry.isoformat() if record.medical_expiry else None,
            "adr_expiry": record.adr_expiry.isoformat() if record.adr_expiry else None,
            "notes": record.notes, "updated_by": record.updated_by,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None},
        "card_expiry_from_downloads": downloaded.isoformat() if downloaded else None,
    }


def _course_view(c: DriverCpcCourse) -> dict:
    return {"id": str(c.id), "course_date": c.course_date.isoformat(), "hours": float(c.hours), "title": c.title,
            "provider": c.provider, "has_certificate": bool(c.certificate_path), "certificate_name": c.certificate_name}


async def visible_drivers_by_id(principal: Principal) -> dict[int, dict]:
    path = "/api/drivers?all=true" if principal.administrator else "/api/drivers"
    drivers = await auth.traccar_get(principal, path)
    return {int(d["id"]): d for d in (drivers or []) if isinstance(d, dict) and "id" in d}


async def _driver(principal: Principal, driver_id: int) -> dict:
    driver = (await visible_drivers_by_id(principal)).get(driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found in your DH FleetView drivers.")
    return driver


async def records_for(session: AsyncSession, drivers: dict[int, dict]) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    ids = list(drivers)
    if not ids:
        return []
    records = {r.traccar_driver_id: r for r in (await session.execute(
        select(DriverRecord).where(DriverRecord.traccar_driver_id.in_(ids)))).scalars().all()}
    courses: dict[int, list[DriverCpcCourse]] = {}
    for c in (await session.execute(select(DriverCpcCourse).where(DriverCpcCourse.traccar_driver_id.in_(ids)))).scalars().all():
        courses.setdefault(c.traccar_driver_id, []).append(c)
    cards = await _card_expiries(session)
    out = [_view(d, records.get(i), courses.get(i, []), cards, today) for i, d in drivers.items()]
    out.sort(key=lambda v: (STATUS_ORDER.get(v["status"], 9), (v["name"] or "").lower()))
    return out


@router.get("/drivers")
async def list_records(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await records_for(session, await visible_drivers_by_id(principal))


@router.get("/drivers/{driver_id}")
async def get_record(driver_id: int, principal: Principal = Depends(require_manager),
                     session: AsyncSession = Depends(get_session)) -> dict:
    driver = await _driver(principal, driver_id)
    view = (await records_for(session, {driver_id: driver}))[0]
    courses = (await session.execute(select(DriverCpcCourse).where(DriverCpcCourse.traccar_driver_id == driver_id)
                                     .order_by(DriverCpcCourse.course_date.desc()))).scalars().all()
    return {**view, "courses": [_course_view(c) for c in courses]}


@router.put("/drivers/{driver_id}")
async def put_record(driver_id: int, body: RecordIn, principal: Principal = Depends(require_manager),
                     session: AsyncSession = Depends(get_session)) -> dict:
    await _driver(principal, driver_id)
    record = await session.get(DriverRecord, driver_id)
    if record is None:
        record = DriverRecord(traccar_driver_id=driver_id)
        session.add(record)
    for field, value in body.model_dump().items():
        setattr(record, field, (value.strip() or None) if isinstance(value, str) else value)
    if record.licence_number:
        record.licence_number = record.licence_number.upper().replace(" ", "")
    record.updated_by, record.updated_at = principal.name, datetime.now(timezone.utc)
    await session.commit()
    return await get_record(driver_id, principal, session)


@router.post("/drivers/{driver_id}/courses", status_code=201)
async def add_course(driver_id: int, body: CourseIn, principal: Principal = Depends(require_manager),
                     session: AsyncSession = Depends(get_session)) -> dict:
    await _driver(principal, driver_id)
    if body.course_date > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="The course date can't be in the future.")
    stored = None
    if body.certificate:
        try:
            stored = media_store.save_document(body.certificate)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Certificate couldn't be saved: {exc}")
    session.add(DriverCpcCourse(
        traccar_driver_id=driver_id, course_date=body.course_date, hours=body.hours, title=body.title.strip(),
        provider=body.provider, certificate_path=stored["storage_path"] if stored else None,
        certificate_name=(body.certificate_name or body.title)[:200] if stored else None,
        certificate_type=stored["content_type"] if stored else None, created_by=principal.name))
    await session.commit()
    return await get_record(driver_id, principal, session)


async def _visible_course(session: AsyncSession, principal: Principal, course_id: uuid.UUID) -> DriverCpcCourse:
    course = await session.get(DriverCpcCourse, course_id)
    if course is None or course.traccar_driver_id not in await visible_drivers_by_id(principal):
        raise HTTPException(status_code=404, detail="Course not found.")
    return course


@router.delete("/courses/{course_id}")
async def delete_course(course_id: uuid.UUID, principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)) -> dict:
    course = await _visible_course(session, principal, course_id)
    await session.delete(course)
    await session.commit()
    return {"deleted": True}


@router.get("/courses/{course_id}/certificate")
async def course_certificate(course_id: uuid.UUID, principal: Principal = Depends(require_manager),
                             session: AsyncSession = Depends(get_session)) -> Response:
    course = await _visible_course(session, principal, course_id)
    if not course.certificate_path:
        raise HTTPException(status_code=404, detail="No certificate on this course.")
    return Response(content=media_store.read(course.certificate_path), media_type=course.certificate_type or "application/octet-stream",
                    headers={"Content-Disposition": "inline"})


@router.get("/summary")
async def summary(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)) -> dict:
    rows = await list_records(principal, session)
    items = [i for r in rows for i in r["items"].values()]
    return {
        "drivers": len(rows),
        "expired": sum(1 for i in items if i["status"] in ("expired", "overdue")),
        "due_soon": sum(1 for i in items if i["status"] == "due_soon"),
        "missing": sum(1 for r in rows if any(i["status"] == "missing" for i in r["items"].values())),
        "licence_checks_due": sum(1 for r in rows if r["items"]["licence_check"]["status"] in ("overdue", "missing")),
    }
