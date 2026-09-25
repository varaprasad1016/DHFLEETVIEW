"""Watching the owner's own DH FleetView account.

One account must not quietly lose its administrator rights, get switched off,
or disappear. This does not prevent any of that - prevention belongs inside DH
FleetView itself, where the request is actually handled - but it makes it
impossible for such a change to go unnoticed or to stand for long:

  * the account is checked every minute;
  * rights that have been taken away are put back;
  * anything that happens is emailed, and kept on record.

What it deliberately does not do is recreate a deleted account. That would mean
inventing a password, which would leave the owner locked out of an account
bearing their name - worse than the deletion, and it would mask it. A
disappearance is reported loudly instead.

The alert goes out once per distinct problem, not once a minute: an alert that
arrives sixty times an hour stops being read.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mail import EmailSend
from app.services import auth, mailer

logger = logging.getLogger("tacho.guard")

KIND = "account_guard"

# What was seen last time round, for the schedule screen.
last_result: dict = {"ran": False, "why": "has not run yet"}


def protected() -> list[str]:
    """The addresses whose accounts are watched."""
    return [e.strip() for e in (settings.protected_accounts or "").split(",") if e.strip()]


def _key(address: str) -> str:
    return address.strip().lower()


async def _already_told(session: AsyncSession, reference: str) -> bool:
    """Whether this exact problem has already been reported.

    Keyed on what is wrong rather than on when, so a fault that persists is
    reported once and a new fault is reported straight away.
    """
    row = (await session.execute(
        select(EmailSend.id).where(EmailSend.kind == KIND,
                                   EmailSend.reference == reference,
                                   EmailSend.status == "sent"))).first()
    return row is not None


async def _tell(session: AsyncSession, reference: str, subject: str, body: str) -> None:
    """Email the owner that something has happened to the account."""
    if await _already_told(session, reference):
        return
    addresses = [a for a in protected() if mailer.valid(a)]
    for extra in (settings.smtp_from,):
        if mailer.valid(extra) and extra not in addresses:
            addresses.append(extra)

    for address in addresses:
        record = dict(kind=KIND, period_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                      reference=reference, recipient=address, subject=subject[:300],
                      automatic=True)
        try:
            await mailer.send(address, subject, body)
            session.add(EmailSend(**record, status="sent"))
        except mailer.MailError as exc:
            logger.warning("could not raise the alarm to %s: %s", address, exc)
            session.add(EmailSend(**record, status="failed", detail=str(exc)[:1000]))
    await session.commit()


async def check(session: AsyncSession, principal) -> dict:
    """Look at each protected account, put right what can be put right."""
    wanted = protected()
    if not wanted:
        return {"ran": False, "why": "no accounts are protected"}

    users = await auth.traccar_get(principal, "/api/users")
    if users is None:
        # Cannot tell a deleted account from an unreachable server, and must
        # never cry wolf about the former because of the latter.
        return {"ran": False, "why": "DH FleetView would not answer; nothing could be checked"}

    by_email = {_key(u.get("email") or ""): u for u in users if isinstance(u, dict)}
    accounts, repaired, alarms = [], [], []

    for address in wanted:
        user = by_email.get(_key(address))
        if user is None:
            alarms.append({"account": address, "problem": "the account no longer exists"})
            await _tell(
                session, f"missing:{_key(address)}",
                f"URGENT: the {address} account is gone from {settings.white_label_title}",
                f"The account {address} is no longer on {settings.white_label_title}.\n\n"
                f"It was not removed by anything on this server. Someone with access has "
                f"deleted it, either through the app or on the machine itself.\n\n"
                f"It has not been recreated automatically: doing so would mean setting a "
                f"password you do not know, and would hide what happened. Recreate it "
                f"yourself, then check who else holds an administrator login.\n\n"
                f"Checked at {datetime.now(timezone.utc):%d %B %Y %H:%M} UTC.\n")
            continue

        problems, fixes = [], {}
        if not user.get("administrator"):
            problems.append("its administrator rights had been taken away")
            fixes["administrator"] = True
        if user.get("disabled"):
            problems.append("it had been disabled")
            fixes["disabled"] = False
        if user.get("readonly"):
            problems.append("it had been made read-only")
            fixes["readonly"] = False

        if not problems:
            accounts.append({"account": address, "id": user.get("id"), "state": "as it should be"})
            continue

        put_back = False
        try:
            await auth.traccar_send(principal, "PUT", f"/api/users/{user['id']}",
                                    {**user, **fixes})
            put_back = True
            logger.warning("put back rights on %s: %s", address, "; ".join(problems))
        except Exception as exc:  # noqa: BLE001 - report it even if the repair fails
            logger.exception("could not put back rights on %s", address)
            problems.append(f"and it could not be put right automatically: {exc}")

        repaired.append({"account": address, "problems": problems, "restored": put_back})
        accounts.append({"account": address, "id": user.get("id"),
                         "state": "put back" if put_back else "needs attention"})
        await _tell(
            session, f"changed:{_key(address)}:{','.join(sorted(fixes))}",
            f"The {address} account was changed on {settings.white_label_title}",
            f"Something changed the {address} account:\n\n"
            + "".join(f"  - {p}\n" for p in problems)
            + ("\nThis has been put back automatically.\n" if put_back
               else "\nThis could NOT be put back automatically. Please look now.\n")
            + f"\nOnly someone with an administrator login could have done this. "
              f"It is worth checking who else has one.\n\n"
              f"Seen at {datetime.now(timezone.utc):%d %B %Y %H:%M} UTC.\n")

    return {"ran": True, "accounts": accounts, "repaired": repaired, "alarms": alarms,
            "checked_at": datetime.now(timezone.utc).isoformat()}


async def run(session: AsyncSession, principal) -> dict:
    global last_result
    last_result = await check(session, principal)
    return last_result
