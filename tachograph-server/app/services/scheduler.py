"""The things the platform does by itself: invoices and weekly driver reports.

Two jobs run here, each on its own clock:

  invoices        on the first morning after a billing period closes - every
                  three months by default, so 1 January, 1 April, 1 July and
                  1 October - for the period that has just ended.
  driver reports  Monday at six, covering the week that ended on Sunday night.

Both are written to survive the server not being up at the moment they were
due. A job is not "fired at a time"; it has a period it belongs to and a time
that period becomes due, and it runs the first time it is noticed to be due and
not yet done. A machine that was off over the weekend sends Monday's reports
when it comes back on Tuesday, rather than skipping the week in silence.

What has been done is recorded in the database, not in memory, for the same
reason: restarting the API must not re-send a customer their invoice.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
# Named, because `time` here is datetime.time - the class that builds six
# o'clock - and importing the module under the same name silently shadows it.
from time import monotonic
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models.billing import Invoice
from app.models.settings import AppSetting
from app.services import (account_guard, auth, billing, driver_reports, fleet_access,
                          invoicing, mailer)

logger = logging.getLogger("tacho.schedule")
if not logger.handlers:
    # uvicorn configures only its own loggers, and an invoice going out to a
    # customer at six in the morning is exactly the kind of thing that has to
    # be in the log as well as in the database.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s SCHEDULE %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

TICK_SECONDS = 60
STATE_PREFIX = "schedule:"
# How far back a job will reach on the very first run it ever does. Beyond
# this, the period that has already closed is left alone rather than billed
# retrospectively - see _due_now.
FIRST_RUN_GRACE_DAYS = 7


# --- what has run ----------------------------------------------------------

async def _state(session: AsyncSession, job: str) -> dict:
    row = (await session.execute(
        select(AppSetting).where(AppSetting.key == STATE_PREFIX + job))).scalar_one_or_none()
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


async def _remember(session: AsyncSession, job: str, value: dict) -> None:
    key = STATE_PREFIX + job
    row = (await session.execute(
        select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if row is None:
        session.add(AppSetting(key=key, value=value, updated_by="scheduler"))
    else:
        row.value = value
        row.updated_by = "scheduler"
    await session.commit()


# --- the jobs --------------------------------------------------------------

@dataclass
class Due:
    """A period of work, and the moment it becomes due."""
    period: str
    at: datetime
    start: date
    end: date


def now_local() -> datetime:
    return datetime.now(driver_reports.zone())


def invoices_due(today: date) -> Due:
    """The billing period that has closed, and when its invoices are due."""
    months = invoicing.every_months()
    year, month = billing.last_closed_period(today, months)
    start, end = billing.period_range(year, month, months)
    hour = max(0, min(23, int(settings.invoice_send_hour or 6)))
    due_at = datetime.combine(end + timedelta(days=1), time(hour=hour),
                              tzinfo=driver_reports.zone())
    return Due(period=billing.period_key(year, month, months), at=due_at,
               start=start, end=end)


def reports_due(today: date) -> Due:
    """The week that has ended, and when its reports are due to go out."""
    start, end = driver_reports.last_full_week(today)
    weekday = max(1, min(7, int(settings.driver_report_weekday or 1)))
    hour = max(0, min(23, int(settings.driver_report_hour or 6)))
    due_at = datetime.combine(end + timedelta(days=weekday),
                              time(hour=hour), tzinfo=driver_reports.zone())
    return Due(period=driver_reports.week_key(start), at=due_at, start=start, end=end)


async def run_invoices(session: AsyncSession, due: Due, *, automatic: bool = True) -> dict:
    """Raise the period's invoices, and email them if that is switched on.

    Raising is always safe and always happens: a draft invoice harms nobody and
    is there to be checked. Sending is the part that is gated - on the rates and
    VAT number being real, and on the operator having turned automatic sending
    on deliberately.
    """
    principal = auth.service_principal()
    if principal is None:
        return {"ran": False, "why": "no DH FleetView API token is set for the "
                                     "scheduled jobs"}

    year, month = due.end.year, due.end.month
    outcome = await invoicing.raise_for_period(principal, session, year, month,
                                              invoicing.every_months())
    result = {"ran": True, "period": due.period, "raised": outcome["raised"],
              "skipped": outcome["skipped"],
              "contacts_updated": outcome.get("contacts_updated", []),
              "sent": [], "failed": []}

    blocked = invoicing.not_ready()
    if blocked:
        result["not_sent_because"] = blocked
        return result
    if automatic and not settings.invoice_auto_send:
        result["not_sent_because"] = ["automatic sending is switched off "
                                      "(INVOICE_AUTO_SEND)"]
        return result

    # Every draft that covers this period, not only the ones just raised: an
    # invoice left unsent by an earlier failed run is still owed to the customer.
    drafts = (await session.execute(
        select(Invoice).where(Invoice.period_start <= due.end,
                              Invoice.period_end >= due.start,
                              Invoice.status != "sent"))).scalars().all()
    for invoice in drafts:
        try:
            to = await invoicing.email_invoice(session, invoice, automatic=automatic)
            result["sent"].append({"number": invoice.number, "to": to,
                                   "account": invoice.account_name})
        except mailer.MailError as exc:
            logger.warning("invoice %s could not be emailed: %s", invoice.number, exc)
            result["failed"].append({"number": invoice.number,
                                     "account": invoice.account_name, "why": str(exc)})
    return result


async def run_driver_reports(session: AsyncSession, due: Due, *,
                             automatic: bool = True) -> dict:
    """Build and email each account its drivers' reports for the week."""
    principal = auth.service_principal()
    if principal is None:
        return {"ran": False, "why": "no DH FleetView API token is set for the "
                                     "scheduled jobs"}
    if not mailer.configured():
        return {"ran": False, "why": "no mail server is set up"}

    result = {"ran": True, "period": due.period, "sent": [], "failed": [], "skipped": []}
    for account in await driver_reports.accounts_to_report(principal):
        name = account["name"] or f"account {account['user_id']}"
        try:
            week = await driver_reports.week_for_account(
                session, principal, account["user_id"], name, account["email"],
                due.start, due.end)
        except Exception as exc:  # noqa: BLE001 - one account must not stop the rest
            logger.exception("could not build the week for %s", name)
            result["failed"].append({"account": name, "why": str(exc)})
            continue

        if not week.reports:
            result["skipped"].append({"account": name, "why": "no driver worked this week"})
            continue
        if automatic and await driver_reports.already_sent(
                session, due.period, str(account["user_id"])):
            result["skipped"].append({"account": name, "why": "already sent this week"})
            continue

        try:
            to = await driver_reports.send_week(session, week, due.start, due.end,
                                                automatic=automatic)
            result["sent"].append({"account": name, "to": to,
                                   "drivers": len(week.reports),
                                   "infringements": week.total_infringements})
        except mailer.MailError as exc:
            logger.warning("the week could not be emailed to %s: %s", name, exc)
            result["failed"].append({"account": name, "why": str(exc)})
    return result


JOBS: dict[str, tuple[Callable[[date], Due], Callable[..., Awaitable[dict]], str]] = {
    "invoices": (invoices_due, run_invoices, "Invoices"),
    "driver_reports": (reports_due, run_driver_reports, "Weekly driver reports"),
}


def enabled(job: str) -> bool:
    if not settings.schedule_enabled:
        return False
    if job == "driver_reports":
        return bool(settings.driver_report_auto_send)
    return True


# --- the loop --------------------------------------------------------------

async def _due_now(session: AsyncSession, job: str, now: datetime) -> Due | None:
    """The work this job owes right now, or None if it is up to date."""
    due = JOBS[job][0](now.date())
    if now < due.at:
        return None
    state = await _state(session, job)
    if state.get("period") == due.period and state.get("status") == "done":
        return None

    # The first time a job ever runs, it starts from now. Without this, turning
    # automatic sending on in October would find that the quarter which closed
    # in July was never invoiced and bill every customer for it - a period
    # nobody was expecting an invoice for, and in all likelihood one they have
    # already been billed for by other means. Once the job has a history,
    # catching up is exactly what is wanted, and it does.
    if not state and (now - due.at) > timedelta(days=FIRST_RUN_GRACE_DAYS):
        logger.info("%s: starting from now; %s closed on %s and is left alone",
                    job, due.period, due.end)
        await _remember(session, job, {
            "period": due.period, "status": "done",
            "last_attempt": now.isoformat(),
            "covering": {"start": due.start.isoformat(), "end": due.end.isoformat()},
            "summary": "left alone - it closed before automatic sending was set up",
        })
        return None
    # A job that failed is retried, but not every minute: a mail server that is
    # down stays down for a while, and an hourly retry is enough.
    if state.get("period") == due.period and state.get("last_attempt"):
        try:
            last = datetime.fromisoformat(state["last_attempt"])
            if (now - last) < timedelta(hours=1):
                return None
        except ValueError:
            pass
    return due


async def run_job(session: AsyncSession, job: str, due: Due, *,
                  automatic: bool = True) -> dict:
    """Run one job and write down what happened."""
    runner = JOBS[job][1]
    started = now_local()
    try:
        outcome = await runner(session, due, automatic=automatic)
    except Exception as exc:  # noqa: BLE001 - the loop must survive anything
        logger.exception("the %s job failed", job)
        outcome = {"ran": False, "why": str(exc)}

    if automatic:
        finished = outcome.get("ran") and not outcome.get("failed")
        await _remember(session, job, {
            "period": due.period,
            "status": "done" if finished else "incomplete",
            "last_attempt": started.isoformat(),
            "covering": {"start": due.start.isoformat(), "end": due.end.isoformat()},
            "summary": _summary(job, outcome),
        })
    return outcome


def _summary(job: str, outcome: dict) -> str:
    """One line a person can read on the schedule screen."""
    if not outcome.get("ran"):
        return f"did not run: {outcome.get('why', 'unknown reason')}"
    sent, failed = len(outcome.get("sent", [])), len(outcome.get("failed", []))
    parts = []
    if job == "invoices":
        parts.append(f"{len(outcome.get('raised', []))} raised")
    parts.append(f"{sent} emailed")
    if failed:
        parts.append(f"{failed} failed")
    if outcome.get("contacts_updated"):
        parts.append(f"{len(outcome['contacts_updated'])} address(es) updated")
    if outcome.get("not_sent_because"):
        parts.append("not sent: " + "; ".join(outcome["not_sent_because"]))
    return ", ".join(parts)


_last_share = [0.0]


async def _share_new_vehicles() -> None:
    """Keep the standing accounts seeing the whole fleet.

    Not tied to a period like the other jobs: a vehicle added this morning
    should be visible this morning, so this reconciles on its own short cycle.
    """
    interval = max(30, int(settings.auto_share_seconds or 120))
    if not fleet_access.emails():
        return
    now = monotonic()
    if now - _last_share[0] < interval:
        return
    _last_share[0] = now
    principal = auth.service_principal()
    if principal is None:
        fleet_access.last_result = {"ran": False, "why": "no DH FleetView API token is set"}
        return
    await fleet_access.run(principal)


_last_guard = [0.0]


async def _guard_accounts(session: AsyncSession) -> None:
    """Check the owner's account is still what it should be."""
    interval = max(30, int(settings.account_guard_seconds or 60))
    if not account_guard.protected():
        return
    now = monotonic()
    if now - _last_guard[0] < interval:
        return
    _last_guard[0] = now
    principal = auth.service_principal()
    if principal is None:
        account_guard.last_result = {"ran": False,
                                     "why": "no DH FleetView API token is set"}
        return
    await account_guard.run(session, principal)


async def tick() -> None:
    """One pass: run anything that has fallen due."""
    try:
        await _share_new_vehicles()
    except Exception:  # noqa: BLE001 - sharing must never stop the email jobs
        logger.exception("could not share new vehicles")

    async with SessionLocal() as session:
        try:
            await _guard_accounts(session)
        except Exception:  # noqa: BLE001 - the watch must never stop the jobs
            logger.exception("could not check the protected accounts")

    async with SessionLocal() as session:
        for job in JOBS:
            if not enabled(job):
                continue
            try:
                due = await _due_now(session, job, now_local())
            except Exception:  # noqa: BLE001
                logger.exception("could not work out whether %s is due", job)
                continue
            if due is None:
                continue
            logger.info("running the %s job for %s", job, due.period)
            await run_job(session, job, due)


async def run() -> None:
    """The scheduler itself. Started with the API and cancelled with it."""
    logger.info("scheduler started (%s)", settings.schedule_timezone)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a bad tick must never end the loop
            logger.exception("the scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


def next_due(job: str, done: Due) -> Due:
    """The period after the one just finished, so the screen can say when next.

    Worked out by asking the job the same question a day inside the next
    period, rather than by adding an interval to a date - which is the only way
    to keep month lengths and the clock changes out of it.
    """
    return JOBS[job][0](done.end + timedelta(days=(8 if job == "driver_reports"
                                                   else 32 * invoicing.every_months())))


async def status(session: AsyncSession) -> dict:
    """What is set up, what ran last, and what is due next."""
    now = now_local()
    ready, token_detail = await auth.service_token_works()
    jobs = []
    for job, (when, _runner, label) in JOBS.items():
        due = when(now.date())
        state = await _state(session, job)
        done = state.get("period") == due.period and state.get("status") == "done"
        upcoming = next_due(job, due) if done else due
        jobs.append({
            "job": job, "label": label, "enabled": enabled(job),
            "period": due.period,
            "covers": {"start": due.start.isoformat(), "end": due.end.isoformat()},
            "due_at": due.at.isoformat(),
            "overdue": now >= due.at and not done,
            "next_at": upcoming.at.isoformat(),
            "last_run": state or None,
        })
    return {
        "timezone": settings.schedule_timezone,
        "now": now.isoformat(),
        "enabled": settings.schedule_enabled,
        "mail_ready": mailer.configured(),
        "service_token": {"ready": ready, "detail": token_detail},
        "invoice_every_months": invoicing.every_months(),
        "invoice_auto_send": settings.invoice_auto_send,
        "driver_report_auto_send": settings.driver_report_auto_send,
        "not_ready": invoicing.not_ready(),
        "jobs": jobs,
        "protected_accounts": {"accounts": account_guard.protected(),
                              "last": account_guard.last_result},
        "fleet_access": {"accounts": fleet_access.emails(),
                         "every_seconds": settings.auto_share_seconds,
                         "last": fleet_access.last_result},
    }
