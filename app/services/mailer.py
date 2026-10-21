"""Sending email from the platform.

Only invoices use this today, and an invoice is the sort of email that must
either arrive or be seen to have failed - so nothing here is quiet about a
problem. A failure comes back with the server's own words, which is usually the
whole diagnosis ("authentication failed", "relay denied", "mailbox full").

The message is built separately from the sending, so what goes out can be
checked without a mail server involved.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.config import settings

logger = logging.getLogger("tacho.mail")

TIMEOUT = 30
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(Exception):
    """The message could not be sent, in the mail server's words where possible."""


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def valid(address: str | None) -> bool:
    return bool(address and ADDRESS.match(address.strip()))


def build(to: str, subject: str, body: str,
          attachments: list[tuple[str, bytes, str]] | None = None) -> EmailMessage:
    """One message, ready to send.

    `attachments` are (filename, content, mime subtype) - an invoice is
    ("DH-2026-0001.pdf", <bytes>, "pdf").
    """
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name or None, settings.smtp_from))
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if settings.smtp_reply_to:
        message["Reply-To"] = settings.smtp_reply_to
    message.set_content(body)

    for filename, content, subtype in attachments or []:
        message.add_attachment(content, maintype="application", subtype=subtype,
                               filename=filename)
    return message


def _send(message: EmailMessage) -> None:
    """The blocking part: hand the message to the mail server."""
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls()
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The mail server would not accept those credentials. "
                        "A mailbox with two-step sign-in usually needs an app password "
                        f"rather than the account's own: {_words(exc)}") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"The mail server refused the address: {_words(exc)}") from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"The mail server refused the message: {_words(exc)}") from exc
    except OSError as exc:
        raise MailError(f"The mail server could not be reached: {exc}") from exc


def _words(exc: Exception) -> str:
    """Whatever the server actually said, rather than a Python repr."""
    for part in getattr(exc, "args", ()):
        if isinstance(part, bytes):
            return part.decode("utf-8", errors="replace").strip()
        if isinstance(part, dict) and part:
            first = next(iter(part.values()))
            if isinstance(first, tuple) and len(first) > 1 and isinstance(first[1], bytes):
                return first[1].decode("utf-8", errors="replace").strip()
        if isinstance(part, str) and part:
            return part.strip()
    return str(exc)


async def send(to: str, subject: str, body: str,
               attachments: list[tuple[str, bytes, str]] | None = None) -> str:
    """Send one message. Returns where it went; raises MailError if it did not."""
    if not configured():
        raise MailError("No mail server is set up on this server yet.")
    if not valid(to):
        raise MailError(f"{to or 'That address'} is not an email address.")

    message = build(to.strip(), subject, body, attachments)
    await asyncio.to_thread(_send, message)
    logger.info("sent %r to %s", subject, to)
    return to.strip()
