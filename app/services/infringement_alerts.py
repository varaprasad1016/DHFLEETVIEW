"""Monday texts to drivers who have infringements to read and sign.

The weekly driver report tells the office what happened; this tells the driver.
On the same clock as that report (Monday at six, covering the week that ended
on Sunday night), each driver whose card has thrown up an infringement they
have not yet signed for gets one text: how many are new since the week began,
how many are still waiting, and a link straight to the Infringements screen in
the driver app, where they read it and sign.

Who counts as the driver is decided the way the driver app decides it - by the
driver card number on their login, never by name - so nobody is texted about
somebody else's hours. Rule types the administrator leaves off everyone's
reports are left off here too.

The texts go through the same queue as the camera setup messages (DvrMessage),
tagged with their own command name so the office outbox can tell them apart
and so a re-run of the job does not text anyone twice in a week.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.driver_auth import DriverAccount
from app.models.dvr import DvrMessage
from app.models.infringement_review import InfringementReview
from app.models.tacho import Infringement, TachoFile
from app.services import driver_reports, report_settings

COMMAND = "infringement_alert"
# Two texts' worth. The wording below stays well inside it; the cap is there
# so a long operator name or URL can never push a message into a third part.
MAX_LENGTH = 300


def card_key(value: str | None) -> str:
    """Driver card numbers compare on the 14-character driver identification
    (the last two characters are replacement/renewal indexes)."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())[:14]


@dataclass
class Alert:
    account_id: uuid.UUID
    name: str
    phone: str | None
    new: int            # raised since the week began
    outstanding: int    # unsigned altogether, the new ones included


def plan(accounts, refs_by_card: dict[str, set[str]], infringements, signed: set,
         hidden: set[str], since: datetime) -> list[Alert]:
    """Who needs a text, and what it should say.

    accounts       (id, name, phone, unique_id, active) per driver login
    refs_by_card   driver card key -> the tachograph driver refs its downloads carry
    infringements  (id, driver_ref, rule, status, created_at)
    signed         ids of infringements that already carry a driver signature
    hidden         rule codes left off everyone's reports
    since          when the week began; anything raised from then on is "new"
    """
    waiting: dict[str, list] = {}
    for inf_id, ref, rule, status, created_at in infringements:
        if status == "dismissed" or rule in hidden or inf_id in signed:
            continue
        waiting.setdefault(ref, []).append(created_at)

    alerts = []
    for account_id, name, phone, unique_id, active in accounts:
        if not active:
            continue
        key = card_key(unique_id)
        if len(key) < 14:
            continue
        mine = [t for ref in refs_by_card.get(key, ()) for t in waiting.get(ref, ())]
        if not mine:
            continue
        alerts.append(Alert(account_id=account_id, name=name, phone=(phone or "").strip() or None,
                            new=sum(1 for t in mine if t >= since), outstanding=len(mine)))
    alerts.sort(key=lambda a: a.name.lower())
    return alerts


def app_link() -> str:
    return settings.bridge_public_url.rstrip("/") + "/driver#/infringements"


def message(alert: Alert) -> str:
    """The text itself. Plain words, the numbers that matter, and the link."""
    first = (alert.name or "").split(" ")[0] or "Driver"
    older = alert.outstanding - alert.new
    if alert.new:
        what = f"{alert.new} new drivers' hours infringement{'s' if alert.new != 1 else ''} from last week"
        if older:
            what += f" and {older} older one{'s' if older != 1 else ''} still waiting"
    else:
        what = (f"{alert.outstanding} drivers' hours infringement{'s' if alert.outstanding != 1 else ''}"
                " still waiting for your signature")
    text = (f"DH FleetView: {first}, you have {what}. Please read and sign in the driver app: "
            f"{app_link()}")
    return text[:MAX_LENGTH]


async def _refs_by_card(session: AsyncSession) -> dict[str, set[str]]:
    rows = (await session.execute(
        select(TachoFile.card_number, TachoFile.driver_ref)
        .where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None),
               TachoFile.driver_ref.is_not(None)))).all()
    out: dict[str, set[str]] = {}
    for card, ref in rows:
        key = card_key(card)
        if len(key) >= 14:
            out.setdefault(key, set()).add(ref)
    return out


async def _already_texted(session: AsyncSession, since: datetime) -> set[uuid.UUID]:
    """Drivers texted this period already - a job retried after a partial
    failure must not send the ones that went the first time again."""
    rows = (await session.execute(
        select(DvrMessage.queued_by).where(DvrMessage.command_name == COMMAND,
                                           DvrMessage.queued_at >= since,
                                           DvrMessage.status.in_(("queued", "sending", "sent"))))).all()
    out = set()
    for (queued_by,) in rows:
        try:
            out.add(uuid.UUID((queued_by or "").split(":")[-1]))
        except ValueError:
            continue
    return out


async def run(session: AsyncSession, due, *, automatic: bool = True) -> dict:
    """Queue this week's texts. The shape of the result is what the schedule
    screen and the job log expect: sent / failed / skipped, by driver."""
    result = {"ran": True, "period": due.period, "sent": [], "failed": [], "skipped": []}
    if not settings.sms_url:
        return {"ran": False, "why": "no SMS provider is set up (SMS_URL)"}

    tz = driver_reports.zone()
    since = datetime.combine(due.start, time(0), tzinfo=tz)
    accounts = (await session.execute(
        select(DriverAccount.id, DriverAccount.name, DriverAccount.phone,
               DriverAccount.unique_id, DriverAccount.active))).all()
    infringements = (await session.execute(
        select(Infringement.id, Infringement.driver_ref, Infringement.rule,
               Infringement.status, Infringement.created_at))).all()
    signed = set((await session.execute(
        select(InfringementReview.infringement_id)
        .where(InfringementReview.driver_signed_at.is_not(None)))).scalars().all())
    hidden, _ = await report_settings.hidden_for(session, None)
    alerts = plan(accounts, await _refs_by_card(session), infringements, signed, hidden, since)
    done = await _already_texted(session, due.at - timedelta(hours=1))

    for alert in alerts:
        entry = {"driver": alert.name, "new": alert.new, "outstanding": alert.outstanding}
        if alert.account_id in done:
            result["skipped"].append({**entry, "why": "already texted this week"})
            continue
        if not alert.phone:
            result["skipped"].append({**entry, "why": "no mobile number on the driver login"})
            continue
        session.add(DvrMessage(to_number=alert.phone, body=message(alert), command_name=COMMAND,
                               device_name=alert.name,
                               queued_by=f"scheduler:{alert.account_id}"))
        result["sent"].append({**entry, "to": alert.phone})
    await session.commit()
    return result
