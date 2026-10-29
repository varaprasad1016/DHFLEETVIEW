"""Which tachograph data an office user may see.

Tachograph downloads are filed by card holder / vehicle registration, not by
DH FleetView account, so each company's share is worked out from its own
DH FleetView records:

- driver-card files whose card number matches one of the user's drivers
  (driver identifier = driver card number; first 14 characters compared),
- vehicle-unit files whose registration matches one of the user's vehicles,
- and any file the user uploaded themselves.

DH FleetView administrators (the super administrator) see everything.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tacho import Infringement, TachoActivity, TachoFile
from app.services import auth, modules


def card_key(value: str | None) -> str:
    """Driver card numbers compare on the 14-character driver identification
    (the last two characters are replacement/renewal indexes)."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())[:14]


def reg_key(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def device_regs(device: dict) -> set[str]:
    attrs = device.get("attributes") or {}
    values = [device.get("name"), attrs.get("registration"), attrs.get("plate"), attrs.get("licensePlate")]
    return {k for k in (reg_key(v) for v in values if isinstance(v, str)) if len(k) >= 2}


def primary_reg(device: dict) -> str:
    """The registration a vehicle is listed under: its registration attribute, else its name."""
    attrs = device.get("attributes") or {}
    for value in (attrs.get("registration"), attrs.get("plate"), attrs.get("licensePlate"), device.get("name")):
        key = reg_key(value) if isinstance(value, str) else ""
        if len(key) >= 2:
            return key
    return ""


@dataclass
class TachoScope:
    everything: bool
    file_ids: set[uuid.UUID] = field(default_factory=set)
    driver_refs: set[str] = field(default_factory=set)
    drivers: list[dict] = field(default_factory=list)    # the user's DH FleetView drivers
    devices: list[dict] = field(default_factory=list)    # the user's DH FleetView vehicles
    cards: set[str] = field(default_factory=set)         # their drivers' card keys
    regs: set[str] = field(default_factory=set)          # their vehicles' registrations
    device_uids: set[str] = field(default_factory=set)   # their trackers' identifiers

    def allows_live(self, card_number: str | None, vehicle_reg: str | None, device_uid: str | None) -> bool:
        """Live FMC650 data: your driver's card, or one of your vehicles."""
        return (self.everything or (card_number is not None and card_key(card_number) in self.cards)
                or (vehicle_reg is not None and reg_key(vehicle_reg) in self.regs)
                or (device_uid is not None and device_uid in self.device_uids))

    def files(self):
        return true() if self.everything else (TachoFile.id.in_(self.file_ids) if self.file_ids else false())

    def activities(self):
        return true() if self.everything else (
            TachoActivity.source_file_id.in_(self.file_ids) if self.file_ids else false())

    def infringements(self):
        if self.everything:
            return true()
        parts = []
        if self.file_ids:
            parts.append(Infringement.source_file_id.in_(self.file_ids))
        if self.driver_refs:
            # The same card uploaded by two companies keeps one set of infringements.
            parts.append(Infringement.driver_ref.in_(self.driver_refs))
        return or_(*parts) if parts else false()

    def allows_file(self, file_id: uuid.UUID | None) -> bool:
        return self.everything or (file_id is not None and file_id in self.file_ids)

    def allows_infringement(self, inf: Infringement) -> bool:
        return (self.everything or (inf.source_file_id is not None and inf.source_file_id in self.file_ids)
                or inf.driver_ref in self.driver_refs)


async def scope_for(session: AsyncSession, principal: auth.Principal) -> TachoScope:
    if modules.is_super_admin(principal):
        return TachoScope(everything=True)
    drivers = await auth.visible_drivers(principal)
    devices = await auth.visible_devices(principal)
    cards = {k for k in (card_key(d.get("uniqueId")) for d in drivers) if len(k) == 14}
    regs = set().union(*(device_regs(d) for d in devices)) if devices else set()
    rows = (await session.execute(select(
        TachoFile.id, TachoFile.file_kind, TachoFile.card_number, TachoFile.vehicle_ref,
        TachoFile.driver_ref, TachoFile.uploaded_by_user_id))).all()
    scope = TachoScope(everything=False, drivers=drivers, devices=devices, cards=cards, regs=regs,
                       device_uids={str(d.get("uniqueId")) for d in devices if d.get("uniqueId")})
    for fid, kind, card, vehicle, driver_ref, uploader in rows:
        mine = (
            (principal.user_id is not None and uploader == principal.user_id)
            or (kind == "driver_card" and len(card_key(card)) == 14 and card_key(card) in cards)
            or (kind == "vehicle_unit" and reg_key(vehicle) in regs)
        )
        if mine:
            scope.file_ids.add(fid)
            if kind == "driver_card" and driver_ref:
                scope.driver_refs.add(driver_ref)
    return scope


async def scope_for_user_id(session: AsyncSession, principal: auth.Principal,
                            user_id: int) -> TachoScope:
    """One office account's share, worked out by somebody else.

    `scope_for` asks Traccar what the caller can see, which only works when the
    caller is the account itself. The scheduled weekly report is nobody: it
    runs on its own and has to build each account's share in turn, so it asks
    an administrator's identity for the drivers and vehicles linked to that
    account instead. The result is the same set of files the account would see
    for itself.
    """
    drivers = await auth.traccar_get(principal, f"/api/drivers?userId={int(user_id)}") or []
    devices = await auth.traccar_get(principal, f"/api/devices?userId={int(user_id)}") or []
    cards = {k for k in (card_key(d.get("uniqueId")) for d in drivers) if len(k) == 14}
    regs = set().union(*(device_regs(d) for d in devices)) if devices else set()

    scope = TachoScope(everything=False, drivers=drivers, devices=devices, cards=cards,
                       regs=regs,
                       device_uids={str(d.get("uniqueId")) for d in devices if d.get("uniqueId")})
    rows = (await session.execute(select(
        TachoFile.id, TachoFile.file_kind, TachoFile.card_number, TachoFile.vehicle_ref,
        TachoFile.driver_ref, TachoFile.uploaded_by_user_id))).all()
    for fid, kind, card, vehicle, driver_ref, uploader in rows:
        mine = (
            uploader == user_id
            or (kind == "driver_card" and len(card_key(card)) == 14 and card_key(card) in cards)
            or (kind == "vehicle_unit" and reg_key(vehicle) in regs)
        )
        if mine:
            scope.file_ids.add(fid)
            if kind == "driver_card" and driver_ref:
                scope.driver_refs.add(driver_ref)
    return scope


async def scope_for_card(session: AsyncSession, card: str | None) -> TachoScope:
    """A driver's own driver-card files (driver app)."""
    key = card_key(card)
    scope = TachoScope(everything=False)
    if len(key) < 14:
        return scope
    rows = (await session.execute(
        select(TachoFile.id, TachoFile.card_number, TachoFile.driver_ref)
        .where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None)))).all()
    for fid, number, driver_ref in rows:
        if card_key(number) == key:
            scope.file_ids.add(fid)
            if driver_ref:
                scope.driver_refs.add(driver_ref)
    return scope
