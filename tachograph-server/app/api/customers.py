"""Customer tenancy and tachograph assignment API.

The bridge continues to own PC/SC and USB card access on Windows. This API
registers which customer owns a vehicle, company card, bridge, and download.
Until the platform user-authentication layer is added, customer-scoped
requests must send the matching ``X-Company-ID`` header.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license
from app.database import get_session
from app.models.core import Company, CompanyCard, Driver, DriverCompany, TbaInstance, Vehicle
from app.models.tacho import TachoFile

router = APIRouter(prefix="/api/customers", tags=["customers"], dependencies=[Depends(require_license)])


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_code: str | None = Field(default=None, max_length=40)


class VehicleIn(BaseModel):
    registration: str = Field(min_length=1, max_length=20)
    vin: str | None = Field(default=None, max_length=17)
    tachograph_serial: str | None = Field(default=None, max_length=50)
    fmc650_imei: str | None = Field(default=None, max_length=15)


class CardIn(BaseModel):
    card_id: str = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=100)
    number: str | None = Field(default=None, max_length=20)


class BridgeIn(BaseModel):
    tba_id: str = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=100)
    ws_url: str | None = Field(default=None, max_length=500)


class DriverIn(BaseModel):
    card_number: str = Field(min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=100)


async def company_scope(company_id: uuid.UUID, x_company_id: str | None = Header(default=None)) -> uuid.UUID:
    if not x_company_id:
        raise HTTPException(status_code=400, detail="X-Company-ID header is required.")
    try:
        selected = uuid.UUID(x_company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Company-ID is not a valid UUID.") from exc
    if selected != company_id:
        raise HTTPException(status_code=403, detail="The selected customer does not match the request scope.")
    return selected


def _company_view(c: Company) -> dict:
    return {"id": str(c.id), "name": c.name, "account_code": c.account_code, "active": c.active}


def _vehicle_view(v: Vehicle) -> dict:
    return {
        "id": str(v.id), "company_id": str(v.company_id), "registration": v.registration,
        "vin": v.vin, "tachograph_serial": v.tachograph_serial,
        "fmc650_imei": v.fmc650_imei, "active": v.active,
    }


@router.post("", status_code=201)
async def create_customer(body: CompanyIn, session: AsyncSession = Depends(get_session)) -> dict:
    company = Company(name=body.name.strip(), account_code=body.account_code)
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return _company_view(company)


@router.get("")
async def list_customers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(Company).order_by(Company.name))).scalars().all()
    return [_company_view(c) for c in rows]


@router.get("/{company_id}")
async def get_customer(company_id: uuid.UUID, _: uuid.UUID = Depends(company_scope),
                       session: AsyncSession = Depends(get_session)) -> dict:
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return _company_view(company)


@router.post("/{company_id}/vehicles", status_code=201)
async def add_vehicle(company_id: uuid.UUID, body: VehicleIn, _: uuid.UUID = Depends(company_scope),
                      session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    registration = "".join(body.registration.upper().split())
    existing = (await session.execute(select(Vehicle).where(
        Vehicle.company_id == company_id, Vehicle.registration == registration))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="That vehicle is already assigned to this customer.")
    vehicle = Vehicle(company_id=company_id, registration=registration, vin=body.vin,
                      tachograph_serial=body.tachograph_serial, fmc650_imei=body.fmc650_imei)
    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)
    return _vehicle_view(vehicle)


@router.get("/{company_id}/vehicles")
async def list_vehicles(company_id: uuid.UUID, _: uuid.UUID = Depends(company_scope),
                        session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(Vehicle).where(
        Vehicle.company_id == company_id).order_by(Vehicle.registration))).scalars().all()
    return [_vehicle_view(v) for v in rows]


@router.post("/{company_id}/cards", status_code=201)
async def add_company_card(company_id: uuid.UUID, body: CardIn, _: uuid.UUID = Depends(company_scope),
                           session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    card = (await session.execute(select(CompanyCard).where(
        CompanyCard.card_id == body.card_id))).scalar_one_or_none()
    if card is not None:
        if card.company_id != company_id:
            raise HTTPException(status_code=409, detail="This company card belongs to another customer.")
        return {"id": str(card.id), "company_id": str(company_id), "card_id": card.card_id,
                "already_registered": True}
    card = CompanyCard(company_id=company_id, card_id=body.card_id, name=body.name, number=body.number)
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return {"id": str(card.id), "company_id": str(company_id), "card_id": card.card_id, "name": card.name}


@router.post("/{company_id}/bridges", status_code=201)
async def register_bridge(company_id: uuid.UUID, body: BridgeIn, _: uuid.UUID = Depends(company_scope),
                          session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    bridge = (await session.execute(select(TbaInstance).where(
        TbaInstance.tba_id == body.tba_id))).scalar_one_or_none()
    if bridge is None:
        bridge = TbaInstance(company_id=company_id, tba_id=body.tba_id,
                             name=body.name, ws_url=body.ws_url)
        session.add(bridge)
    elif bridge.company_id != company_id:
        raise HTTPException(status_code=409, detail="This bridge is registered to another customer.")
    await session.commit()
    await session.refresh(bridge)
    return {"id": str(bridge.id), "company_id": str(company_id), "tba_id": bridge.tba_id,
            "name": bridge.name, "ws_url": bridge.ws_url, "connected": bridge.connected}


@router.post("/{company_id}/drivers", status_code=201)
async def assign_driver(company_id: uuid.UUID, body: DriverIn, _: uuid.UUID = Depends(company_scope),
                        session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    driver = (await session.execute(select(Driver).where(
        Driver.card_number == body.card_number))).scalar_one_or_none()
    if driver is None:
        driver = Driver(card_number=body.card_number, name=body.name)
        session.add(driver)
        await session.flush()
    elif body.name and not driver.name:
        driver.name = body.name
    link = await session.get(DriverCompany, {"driver_id": driver.id, "company_id": company_id})
    if link is None:
        session.add(DriverCompany(driver_id=driver.id, company_id=company_id))
    await session.commit()
    return {"driver_id": str(driver.id), "company_id": str(company_id),
            "card_number": driver.card_number, "name": driver.name}


@router.get("/{company_id}/files")
async def list_customer_files(company_id: uuid.UUID, _: uuid.UUID = Depends(company_scope),
                              session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(TachoFile).where(
        TachoFile.company_id == company_id).order_by(TachoFile.created_at.desc()).limit(500))).scalars().all()
    return [{"id": str(f.id), "filename": f.filename, "file_kind": f.file_kind,
             "company_id": str(company_id), "vehicle_id": str(f.vehicle_id) if f.vehicle_id else None,
             "vehicle_ref": f.vehicle_ref, "driver_ref": f.driver_ref, "parsed": f.parsed,
             "sha256": f.sha256, "created_at": f.created_at.isoformat() if f.created_at else None}
            for f in rows]
