"""The one mailbox the platform sends from.

Everything that emails anyone - invoices today, anything added later - goes
through app.services.mailer and out of the single address configured here.
That is deliberate: a customer should see one sender from this company, and a
mailbox that stops working should break in one place rather than in several.

GET  /api/mail/settings          what is set up, without the password
POST /api/mail/test              send a test message and report what the server said
GET  /api/mail/schedule          what goes out by itself, and when
POST /api/mail/schedule/{job}/run   run one of those jobs now
GET  /api/mail/sends             what has been sent, failures included
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.mail import EmailSend
from app.services import mailer, modules, scheduler
from app.services.auth import Principal

logger = logging.getLogger("tacho.mail")

router = APIRouter(prefix="/api/mail", tags=["mail"])


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403,
                            detail="Only a super administrator can see the mail settings.")


@router.get("/settings")
async def mail_settings(principal: Principal = Depends(require_manager)):
    """What the platform sends as. The password is never returned."""
    _require_super(principal)
    return {
        "ready": mailer.configured(),
        "host": settings.smtp_host or None,
        "port": settings.smtp_port,
        "starttls": settings.smtp_starttls,
        "username": settings.smtp_username or None,
        "password_set": bool(settings.smtp_password),
        "from": settings.smtp_from or None,
        "from_name": settings.smtp_from_name or None,
        "reply_to": settings.smtp_reply_to or None,
    }


@router.get("/schedule")
async def schedule(principal: Principal = Depends(require_manager),
                   session: AsyncSession = Depends(get_session)):
    """What goes out by itself, when it last went, and when it goes next."""
    _require_super(principal)
    return await scheduler.status(session)


@router.get("/sends")
async def recent_sends(limit: int = Query(50, ge=1, le=500),
                       kind: str | None = None,
                       principal: Principal = Depends(require_manager),
                       session: AsyncSession = Depends(get_session)):
    """Every email the platform has sent, newest first - failures included."""
    _require_super(principal)
    query = select(EmailSend).order_by(EmailSend.sent_at.desc()).limit(limit)
    if kind:
        query = query.where(EmailSend.kind == kind)
    rows = (await session.execute(query)).scalars().all()
    return {"sends": [{
        "id": str(row.id), "kind": row.kind, "period": row.period_key,
        "reference": row.reference, "account": row.account_name,
        "recipient": row.recipient, "subject": row.subject, "status": row.status,
        "detail": row.detail, "automatic": row.automatic,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    } for row in rows]}


@router.post("/schedule/{job}/run")
async def run_now(job: str, body: dict = Body(default={}),
                  principal: Principal = Depends(require_manager),
                  session: AsyncSession = Depends(get_session)):
    """Run a scheduled job now, rather than waiting for its morning.

    This is the on-demand version of exactly what the scheduler does, so what
    goes out is the same either way. Because a person asked for it, it is not
    deduplicated - pressing the button twice sends twice, which is the point
    when the first attempt failed.
    """
    _require_super(principal)
    if job not in scheduler.JOBS:
        raise HTTPException(status_code=404,
                            detail=f"There is no {job!r} job. Try: "
                                   + ", ".join(scheduler.JOBS))
    due = scheduler.JOBS[job][0](scheduler.now_local().date())
    outcome = await scheduler.run_job(session, job, due, automatic=False)
    logger.info("%s ran the %s job by hand for %s", principal.email, job, due.period)
    return {"job": job, "period": due.period,
            "covers": {"start": due.start.isoformat(), "end": due.end.isoformat()},
            **outcome}


@router.post("/test")
async def test_email(body: dict = Body(default={}),
                     principal: Principal = Depends(require_manager)):
    """Send a test message, so credentials are proved before a customer is emailed."""
    _require_super(principal)
    to = (body.get("to") or principal.email or "").strip()
    if not mailer.valid(to):
        raise HTTPException(status_code=400,
                            detail=f"{to or 'No address'} is not an email address.")

    try:
        await mailer.send(
            to, f"Test from {settings.company_name}",
            "This is a test message from DH FleetView.\n\n"
            f"If it arrived, the mail settings are working and invoices will be sent "
            f"from {settings.smtp_from}.\n")
    except mailer.MailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("%s sent a test email to %s", principal.email, to)
    return {"sent_to": to, "sent_from": settings.smtp_from}
