"""The weekly driver report, emailed to the operator on a Monday morning.

An operator has to review drivers' hours and debrief infringements, and the
week they are reviewing is the one that ended on Sunday night. So this builds
the same report the Hours page draws - one page per driver, per day, with the
week's infringements and the signature lines - and emails it first thing on
Monday to the address the account was registered with.

Only drivers who actually worked in the week are included. A report for a
driver who was on holiday says nothing and would train the operator to ignore
the email.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mail import EmailSend
from app.models.tacho import TachoActivity, TachoFile
from app.services import auth, mailer, report_settings, tacho_pdf, tacho_scope

logger = logging.getLogger("tacho.reports")

KIND = "driver_report"


def zone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.schedule_timezone or "Europe/London")
    except Exception:  # noqa: BLE001 - a bad zone must not stop the reports
        logger.warning("unknown schedule timezone %r; using Europe/London",
                       settings.schedule_timezone)
        return ZoneInfo("Europe/London")


def last_full_week(today: date) -> tuple[date, date]:
    """The Monday-to-Sunday week that had ended before `today`.

    On a Monday this is the week just gone, which is the point of sending it on
    a Monday. Run on any other day it still means the last complete week, so a
    report asked for by hand on a Wednesday is not half a week of data.
    """
    monday_this_week = today - timedelta(days=today.isoweekday() - 1)
    start = monday_this_week - timedelta(days=7)
    return start, start + timedelta(days=6)


def week_key(start: date) -> str:
    """How a week is named where it has to be recognised again: 2026-W39."""
    iso_year, iso_week, _ = start.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def week_name(start: date, end: date) -> str:
    """The period in words. A span crossing a year keeps both years, or
    "16 July – 25 June 2026" reads as though it runs backwards."""
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {end.strftime('%B %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%d %B')} – {end.strftime('%d %B %Y')}"
    return f"{start.strftime('%d %B %Y')} – {end.strftime('%d %B %Y')}"


@dataclass
class DriverReport:
    """One driver's report, ready to attach."""
    driver_ref: str
    name: str
    pdf: bytes | None = None
    infringements: int = 0
    problem: str | None = None
    # What the report actually ended up covering. When no dates are asked for
    # this is the whole of the card, which is not knowable until it is built.
    period_from: date | None = None
    period_to: date | None = None
    weeks: int = 0

    @property
    def filename(self) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in (self.name or self.driver_ref))
        return f"{safe.strip('_') or 'driver'}_week.pdf"


@dataclass
class AccountWeek:
    """What one account is being sent for one week."""
    user_id: int
    account: str
    email: str | None
    reports: list[DriverReport] = field(default_factory=list)

    @property
    def with_infringements(self) -> list[DriverReport]:
        return [r for r in self.reports if r.infringements]

    @property
    def total_infringements(self) -> int:
        return sum(r.infringements for r in self.reports)


async def drivers_active(session: AsyncSession, scope: tacho_scope.TachoScope,
                         start: date, end: date) -> list[str]:
    """Card holders in this account's scope who have activity in the week."""
    tz = zone()
    since = datetime.combine(start, time.min, tzinfo=tz)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    rows = (await session.execute(
        select(TachoActivity.driver_ref)
        .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
        .where(TachoFile.file_kind == "driver_card", scope.activities(),
               TachoActivity.ended_at >= since, TachoActivity.started_at < until)
        .distinct())).scalars().all()
    return sorted({r for r in rows if r})


async def build_week(session: AsyncSession, scope: tacho_scope.TachoScope,
                     driver_ref: str, start: date | None, end: date | None,
                     hidden: set[str] | None = None) -> DriverReport:
    """One driver's report, drawn exactly as the Hours page draws it.

    With `start` and `end` given the report covers that span. With both None it
    covers the whole of the card, which is what the Hours page shows when the
    date boxes are left empty - and what the emailed copy has to match, or the
    recipient gets one page where the screen showed a year.
    """
    # Imported here rather than at the top: the report assembly lives with the
    # endpoint that has always served it, and importing it eagerly would have a
    # service depend on the API layer at start-up.
    from app.api.tacho import _report_for

    report = DriverReport(driver_ref=driver_ref, name=driver_ref)
    try:
        data = await _report_for(session, None, driver_ref, start, end, scope, hidden)
    except Exception as exc:  # noqa: BLE001 - one unreadable card must not stop the rest
        logger.warning("could not build the weekly report for %s: %s", driver_ref, exc)
        report.problem = getattr(exc, "detail", None) or str(exc)
        return report

    report.name = (data.get("driver") or {}).get("name") or driver_ref
    report.infringements = sum(
        len(week.get("infringements", [])) + len(week.get("working_time_infringements", []))
        for week in data.get("weeks", []))
    report.weeks = len(data.get("weeks", []))
    period = data.get("period") or {}
    for field_name, key in (("period_from", "from"), ("period_to", "to")):
        try:
            setattr(report, field_name, date.fromisoformat(period[key]))
        except (KeyError, TypeError, ValueError):
            pass
    try:
        report.pdf = tacho_pdf.render(data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not draw the weekly report for %s", driver_ref)
        report.problem = f"the report could not be drawn: {exc}"
    return report


async def week_for_account(session: AsyncSession, principal, user_id: int, account: str,
                           email: str | None, start: date, end: date) -> AccountWeek:
    """Every report one account is due for one week."""
    scope = await tacho_scope.scope_for_user_id(session, principal, user_id)
    hidden, _ = await report_settings.hidden_for(session, user_id)
    week = AccountWeek(user_id=user_id, account=account, email=email)
    for driver_ref in await drivers_active(session, scope, start, end):
        week.reports.append(await build_week(session, scope, driver_ref, start, end, hidden))
    return week


def email_text(week: AccountWeek, start: date, end: date) -> str:
    """What the operator reads before opening anything.

    The counts come first because they decide whether this is a five-minute job
    or a morning's work.
    """
    period = week_name(start, end)
    breached = week.with_infringements
    clean = [r for r in week.reports if not r.infringements and not r.problem]

    lines = [f"Dear {week.account},", "",
             f"Here are the driver reports for {period}.", ""]
    if breached:
        lines.append(f"{len(breached)} driver(s) with infringements to debrief "
                     f"({week.total_infringements} in total):")
        for report in sorted(breached, key=lambda r: -r.infringements):
            lines.append(f"  · {report.name} — {report.infringements} infringement"
                         f"{'s' if report.infringements != 1 else ''}")
        lines.append("")
    else:
        lines += ["No infringements were found this week.", ""]

    if clean:
        lines.append(f"{len(clean)} driver(s) with nothing to answer: "
                     + ", ".join(sorted(r.name for r in clean)))
        lines.append("")

    problems = [r for r in week.reports if r.problem]
    if problems:
        lines.append("These could not be built, and are worth a look on the Hours page:")
        lines += [f"  · {r.name} — {r.problem}" for r in problems]
        lines.append("")

    attached = attachments(week)
    if attached:
        # Say how much is in there. A report covering a year is fifty-odd pages,
        # and the reader should know that before deciding it looks short.
        pages = sum(r.weeks for r in week.reports if r.pdf)
        size = (f", {pages} week{'s' if pages != 1 else ''} in all"
                if pages > 1 else "")
        lines.append(f"{len(attached)} report(s) are attached{size}. Each one carries "
                     "a page per week and the signature lines for the driver debrief.")
    held_back = len([r for r in week.reports if r.pdf]) - len(attached)
    if held_back > 0:
        lines.append(f"{held_back} further report(s) were left off to keep this email "
                     "a sensible size; they are all on the Hours page.")
    lines += ["", "You can see the same reports at any time on the Hours page in "
              f"{settings.white_label_title}.", "",
              settings.company_name, ""]
    return "\n".join(lines)


def attachments(week: AccountWeek) -> list[tuple[str, bytes, str]]:
    """The PDFs to attach, drivers with infringements first.

    A mailbox that rejects a 30 MB email helps nobody, so there is a limit; the
    reports that were left off are named in the message and remain on the Hours
    page. Drivers with something to answer are attached first so the limit can
    only ever drop the uneventful ones.
    """
    ordered = sorted((r for r in week.reports if r.pdf),
                     key=lambda r: (-r.infringements, r.name))
    limit = max(1, int(settings.driver_report_max_attachments or 25))
    taken, names = [], set()
    for report in ordered[:limit]:
        name = report.filename
        # Two drivers whose names reduce to the same filename must not collide,
        # or one silently replaces the other in the email.
        if name in names:
            name = f"{name[:-4]}_{report.driver_ref}.pdf"
        names.add(name)
        taken.append((name, report.pdf, "pdf"))
    return taken


async def already_sent(session: AsyncSession, period: str, reference: str) -> bool:
    row = (await session.execute(
        select(EmailSend.id).where(EmailSend.kind == KIND, EmailSend.period_key == period,
                                   EmailSend.reference == reference,
                                   EmailSend.status == "sent",
                                   EmailSend.automatic.is_(True)))).first()
    return row is not None


async def send_week(session: AsyncSession, week: AccountWeek, start: date, end: date,
                    *, to: str | None = None, automatic: bool = False) -> str:
    """Email one account its week. Raises mailer.MailError if it would not go."""
    address = (to or week.email or "").strip()
    if not mailer.valid(address):
        raise mailer.MailError(
            f"{address or 'No address'} is not an email address. The weekly report "
            f"goes to the address {week.account} is registered with.")

    # One driver reads better named than counted, which is the usual case when
    # somebody sends a report by hand for a debrief.
    single = week.reports[0] if len(week.reports) == 1 else None
    what = f"Driver report — {single.name}" if single else "Driver reports"
    subject = (f"{what}, {week_name(start, end)}"
               + (f" — {week.total_infringements} infringement(s)"
                  if week.total_infringements else " — no infringements"))
    period = week_key(start)
    record = dict(kind=KIND, period_key=period, reference=str(week.user_id),
                  user_id=week.user_id, account_name=week.account, recipient=address,
                  subject=subject[:300], automatic=automatic)
    try:
        await mailer.send(address, subject, email_text(week, start, end), attachments(week))
    except mailer.MailError as exc:
        session.add(EmailSend(**record, status="failed", detail=str(exc)[:1000]))
        await session.commit()
        raise

    session.add(EmailSend(**record, status="sent",
                          detail=f"{len(attachments(week))} report(s), "
                                 f"{week.total_infringements} infringement(s)"))
    await session.commit()
    logger.info("emailed the week %s to %s for %s", period, address, week.account)
    return address


async def accounts_to_report(principal) -> list[dict]:
    """The office accounts a weekly report is due to.

    Everyone with a working DH FleetView login, since the report is a duty of
    the operator rather than something only billed customers get. Accounts with
    no drivers who worked simply produce nothing and are skipped later.
    """
    users = await auth.traccar_get(principal, "/api/users") or []
    return [{"user_id": u["id"], "name": u.get("name") or u.get("email"),
             "email": u.get("email")}
            for u in users if isinstance(u, dict) and u.get("id")
            and not u.get("disabled")]
