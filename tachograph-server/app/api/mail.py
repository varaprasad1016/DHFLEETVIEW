"""The one mailbox the platform sends from.

Everything that emails anyone - invoices today, anything added later - goes
through app.services.mailer and out of the single address configured here.
That is deliberate: a customer should see one sender from this company, and a
mailbox that stops working should break in one place rather than in several.

GET  /api/mail/settings   what is set up, without the password
POST /api/mail/test       send a test message and report what the server said
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.deps import require_manager
from app.config import settings
from app.services import mailer, modules
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
