"""One-click inspection pack: the records an operator is asked for at a DVSA
visit or Traffic Commissioner inquiry, for one company and a date range, as a PDF.

Sections: summary measures; tachograph download status; infringements with
driver sign-off and debrief; working time; walkaround checks and defects;
maintenance records and schedule status; driver records.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta, timezone
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infringement_review import InfringementReview
from app.models.maintenance import MaintenanceRecord
from app.models.tacho import Infringement, TachoFile
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect
from app.services import earned_recognition, infringement_reviews, tacho_compliance, wtd

LONDON = ZoneInfo("Europe/London")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
BAND = colors.HexColor("#f3f4f6")
BAD = colors.HexColor("#b91c1c")
OK = colors.HexColor("#047857")


def _styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK, spaceBefore=4, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=INK, spaceBefore=6, spaceAfter=2),
        "meta": ParagraphStyle("m", parent=base, fontSize=8.5, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("c", parent=base, fontSize=7.2, leading=9, textColor=INK),
        "empty": ParagraphStyle("e", parent=base, fontSize=8, leading=10, textColor=MUTED, fontName="Helvetica-Oblique"),
    }


def _d(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(LONDON).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%d/%m/%Y")


def _hm(minutes) -> str:
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def _table(st: dict, header: list[str], rows: list[list], widths: list[float] | None = None, bad_cols: dict | None = None) -> Table:
    data = [[Paragraph(f"<b>{escape(h)}</b>", st["cell"]) for h in header]]
    for row in rows:
        data.append([c if isinstance(c, Paragraph) else Paragraph(escape(str(c if c is not None else "")), st["cell"]) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _p(st, text, colour=None) -> Paragraph:
    text = escape(str(text))
    return Paragraph(f'<font color="#{colour.hexval()[2:]}">{text}</font>' if colour else text, st["cell"])


async def build(session: AsyncSession, *, tacho_scope, record_scope, vehicles: dict[int, dict], drivers: dict[int, dict],
                start: date, end: date, company: str, generated_by: str, targets: dict[str, float],
                hidden_rules: set[str] | None = None) -> bytes:
    from app.api.driver_records import records_for
    from app.api.maintenance import _schedule_view
    from app.models.maintenance import MaintenanceSchedule
    from app.services.tacho_scope import primary_reg

    st = _styles()
    s_utc = datetime.combine(start, time(0), LONDON).astimezone(timezone.utc)
    e_utc = datetime.combine(end + timedelta(days=1), time(0), LONDON).astimezone(timezone.utc)
    today = datetime.now(LONDON).date()
    story: list = []
    page_w = landscape(A4)[0] - 24 * mm

    # --- cover + summary ------------------------------------------------------------------------
    story += [Spacer(1, 30 * mm), Paragraph("Compliance inspection pack", st["title"]), Spacer(1, 4),
              Paragraph(escape(company), st["h1"]),
              Paragraph(f"Period {_d(start)} to {_d(end)} · generated {datetime.now(LONDON):%d/%m/%Y %H:%M} by {escape(generated_by)}", st["meta"]),
              Spacer(1, 10),
              Paragraph("Contents: 1 Summary measures · 2 Tachograph downloads · 3 Infringements, driver sign-off and debrief · "
                        "4 Working time · 5 Walkaround checks and defects · 6 Maintenance · 7 Driver records", st["meta"]),
              PageBreak()]

    dash = await earned_recognition.dashboard(session, tacho_scope, record_scope, list(vehicles), targets,
                                              period_list=[(start, end)])
    story.append(Paragraph("1. Summary measures for the period", st["h1"]))
    rows = []
    for k in dash["kpis"]:
        v = k["values"][0]
        shown = "No data" if v is None else (f"{v}%" if k["unit"] == "%" else f"{v} {k['unit']}")
        met = k["met"][0]
        rows.append([k["group"], k["label"], _p(st, shown, None if met is None else (OK if met else BAD)),
                     f"{'at least' if k['direction'] == 'min' else 'at most'} {k['target']}{'%' if k['unit'] == '%' else ''}",
                     k["explanation"]])
    story.append(_table(st, ["Area", "Measure", "Result", "Target", "How it's measured"], rows,
                        [30 * mm, 60 * mm, 22 * mm, 26 * mm, page_w - 138 * mm]))
    story.append(Paragraph(f"Safety inspections overdue today: {dash['now']['inspections_overdue']}", st["meta"]))

    # --- downloads --------------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("2. Tachograph downloads (status today)", st["h1"])]
    comp = await tacho_compliance.compliance(session, scope=tacho_scope)
    for title, key, window in (("Driver cards (every 28 days)", "drivers", 28), ("Vehicle units (every 90 days)", "vehicles", 90)):
        story.append(Paragraph(title, st["h2"]))
        items = comp.get(key, [])
        if not items:
            story.append(Paragraph("None on record.", st["empty"]))
            continue
        label = {"compliant": "Up to date", "due_soon": "Due soon", "overdue": "Overdue", "no_data": "No download"}
        story.append(_table(st, ["Name", "Last download", "Days since", "Status"], [
            [i["label"], _d(i["last_download"]) if i["last_download"] else "", i["days_since"] if i["days_since"] is not None else "",
             _p(st, label.get(i["status"], i["status"]), BAD if i["status"] in ("overdue", "no_data") else None)] for i in items],
            [90 * mm, 40 * mm, 25 * mm, 35 * mm]))

    # --- infringements ----------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("3. Infringements, driver sign-off and debrief", st["h1"])]
    infs = (await session.execute(select(Infringement).where(
        tacho_scope.infringements(), Infringement.period_start >= s_utc, Infringement.period_start < e_utc)
        .order_by(Infringement.driver_ref, Infringement.period_start))).scalars().all()
    if hidden_rules:
        infs = [i for i in infs if i.rule not in hidden_rules]
        from app.services.report_settings import RULES
        titles = {c: t for c, t, _ in RULES}
        story.append(Paragraph("Not included, following your weekly report settings: " +
                               escape(", ".join(sorted(titles.get(r, r) for r in hidden_rules))), st["meta"]))
    reviews = await infringement_reviews.reviews_for(session, [i.id for i in infs])
    if infs:
        by_type: dict[str, list] = {}
        for i in infs:
            by_type.setdefault(i.title, []).append(i)
        story.append(Paragraph("By type", st["h2"]))
        story.append(_table(st, ["Infringement", "Count", "Serious or worse", "Driver signed", "Debriefed"], [
            [title, len(items), sum(1 for i in items if i.severity in ("serious", "very_serious")),
             sum(1 for i in items if reviews.get(i.id) and reviews[i.id].driver_signed_at),
             sum(1 for i in items if reviews.get(i.id) and reviews[i.id].debriefed_at)]
            for title, items in sorted(by_type.items(), key=lambda kv: -len(kv[1]))],
            [100 * mm, 20 * mm, 30 * mm, 28 * mm, 25 * mm]))
        story.append(Paragraph("Each infringement", st["h2"]))
    if not infs:
        story.append(Paragraph("No infringements in this period.", st["empty"]))
    else:
        rows = []
        for i in infs:
            v = infringement_reviews.view(reviews.get(i.id))
            rows.append([i.driver_ref, _d(i.period_start), i.severity.replace("_", " "), f"{i.title}. {i.detail or ''}",
                         _d(v["driver_signed_at"]) if v["driver_signed_at"] else _p(st, "Not signed", BAD),
                         (f"{v['debrief_action_label']} ({v['debriefed_by']}, {_d(v['debriefed_at'])})" + (f" — {v['debrief_notes']}" if v["debrief_notes"] else ""))
                         if v["debrief_action"] else _p(st, "No debrief", BAD),
                         i.status])
        story.append(_table(st, ["Driver", "When", "Severity", "Infringement", "Driver signed", "Debrief", "Status"], rows,
                            [38 * mm, 26 * mm, 18 * mm, page_w - 196 * mm, 24 * mm, 72 * mm, 18 * mm]))

    # --- working time -----------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("4. Working time (Road Transport Working Time Regulations)", st["h1"])]
    from app.api.tacho import _card_spans
    spans = await _card_spans(session, tacho_scope, s_utc - timedelta(weeks=17))
    weeks = max(1, (end - start).days // 7 + 1)
    rows = []
    for ref, items in sorted(spans.items()):
        rep = wtd.report(items, weeks=weeks, reference_weeks=17, today=end)
        in_range = [w for w in rep["weeks"] if w["has_data"] and start - timedelta(days=6) <= date.fromisoformat(w["week_start"]) <= end]
        if not in_range:
            continue
        rows.append([ref, len(in_range), _hm(max(w["working_minutes"] for w in in_range)), _hm(in_range[0]["average_minutes"]),
                     sum(1 for w in in_range if any(f["code"] == "week_over_60h" for f in w["flags"])),
                     sum(len(w["night_over_10h"]) for w in in_range),
                     _p(st, "; ".join(sorted({f["label"] for w in in_range for f in w["flags"]})) or "None", BAD if any(w["flags"] for w in in_range) else OK)])
    story.append(_table(st, ["Driver", "Weeks worked", "Longest week", "17-week average (latest)", "Weeks over 60h", "Night work over 10h", "Issues"],
                        rows, [45 * mm, 20 * mm, 22 * mm, 32 * mm, 22 * mm, 26 * mm, page_w - 167 * mm])
                 if rows else Paragraph("No driver card working time in this period.", st["empty"]))

    # --- walkarounds --------------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("5. Walkaround checks and defects", st["h1"])]
    checks = (await session.execute(select(WalkaroundCheck.vehicle_reg, WalkaroundCheck.phase, func.count()).where(
        record_scope.condition(WalkaroundCheck), WalkaroundCheck.created_at >= s_utc, WalkaroundCheck.created_at < e_utc)
        .group_by(WalkaroundCheck.vehicle_reg, WalkaroundCheck.phase))).all()
    per_vehicle: dict[str, dict] = {}
    for reg, phase, n in checks:
        per_vehicle.setdefault(reg, {"pre_use": 0, "end_of_day": 0, "fault_report": 0})[phase] = n
    story.append(Paragraph("Checks per vehicle", st["h2"]))
    story.append(_table(st, ["Vehicle", "Pre-use checks", "End of day checks", "Fault reports"],
                        [[reg, c.get("pre_use", 0), c.get("end_of_day", 0), c.get("fault_report", 0)] for reg, c in sorted(per_vehicle.items())],
                        [50 * mm, 35 * mm, 35 * mm, 35 * mm]) if per_vehicle else Paragraph("No walkaround checks in this period.", st["empty"]))
    defects = (await session.execute(select(WalkaroundDefect, WalkaroundCheck.driver_name).join(
        WalkaroundCheck, WalkaroundCheck.id == WalkaroundDefect.check_id).where(
        record_scope.condition(WalkaroundCheck), WalkaroundDefect.created_at >= s_utc, WalkaroundDefect.created_at < e_utc)
        .order_by(WalkaroundDefect.created_at))).all()
    story.append(Paragraph("Defects reported", st["h2"]))
    story.append(_table(st, ["Reported", "Vehicle", "Driver", "Severity", "Defect", "Rectified", "Rectification"], [
        [_d(d.created_at), d.vehicle_reg, driver or "", _p(st, d.severity, BAD if d.severity == "dangerous" else None),
         f"{d.item}" + (f" — {d.description}" if d.description else ""),
         _d(d.rectified_at) if d.rectified_at else _p(st, "Open", BAD),
         f"{d.rectified_by or ''} {d.rectification_notes or ''}".strip()] for d, driver in defects],
        [28 * mm, 22 * mm, 30 * mm, 18 * mm, page_w - 196 * mm, 28 * mm, 70 * mm]) if defects else Paragraph("No defects reported in this period.", st["empty"]))

    # --- maintenance ---------------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("6. Maintenance", st["h1"])]
    ids = list(vehicles)
    records = (await session.execute(select(MaintenanceRecord).where(
        MaintenanceRecord.traccar_device_id.in_(ids or [-1]), MaintenanceRecord.performed_on >= start,
        MaintenanceRecord.performed_on <= end).order_by(MaintenanceRecord.registration, MaintenanceRecord.performed_on))).scalars().all()
    story.append(Paragraph("Inspections, tests and services carried out", st["h2"]))
    brake = lambda r: "" if r.brake_service_pct is None and r.brake_secondary_pct is None and r.brake_parking_pct is None else \
        f"{r.brake_service_pct or '-'}% / {r.brake_secondary_pct or '-'}% / {r.brake_parking_pct or '-'}%"  # noqa: E731
    story.append(_table(st, ["Vehicle", "Date", "What", "By", "Result", "Brakes (service / secondary / parking)", "Planned date", "Sheet"], [
        [r.registration or vehicles.get(r.traccar_device_id, {}).get("name", ""), _d(r.performed_on), r.label, r.performed_by or "",
         _p(st, (r.result or "").replace("advisories", "pass with advisories"), BAD if r.result == "fail" else None), brake(r),
         _p(st, _d(r.due_on) + (" (late)" if r.due_on and r.performed_on > r.due_on else ""), BAD if r.due_on and r.performed_on > r.due_on else None),
         "on file" if r.document_path else ""] for r in records],
        [26 * mm, 22 * mm, 45 * mm, 38 * mm, 28 * mm, 50 * mm, 30 * mm, page_w - 239 * mm]) if records else Paragraph("No maintenance recorded in this period.", st["empty"]))
    schedules = (await session.execute(select(MaintenanceSchedule).where(
        MaintenanceSchedule.traccar_device_id.in_(ids or [-1]), MaintenanceSchedule.active.is_(True)))).scalars().all()
    story.append(Paragraph("Schedule status today", st["h2"]))
    label = {"overdue": "Overdue", "due_soon": "Due soon", "ok": "Up to date", "not_scheduled": "No date"}
    sched_rows = []
    for s in sorted(schedules, key=lambda x: (x.next_due or date.max)):
        view = _schedule_view(s, today)
        sched_rows.append([primary_reg(vehicles.get(s.traccar_device_id, {})) or s.registration or "", s.label,
                           f"every {s.interval_value} {s.interval_unit}", _d(s.next_due) if s.next_due else "",
                           _p(st, label.get(view["status"], view["status"]), BAD if view["status"] == "overdue" else None)])
    vehicles_without = [v for i, v in vehicles.items() if not any(s.traccar_device_id == i for s in schedules)]
    story.append(_table(st, ["Vehicle", "Item", "Interval", "Next due", "Status"], sched_rows, [30 * mm, 60 * mm, 35 * mm, 30 * mm, 30 * mm])
                 if sched_rows else Paragraph("No maintenance schedules set up.", st["empty"]))
    if vehicles_without:
        story.append(Paragraph("Vehicles with no maintenance schedule: " + escape(", ".join(sorted(v.get("name") or "" for v in vehicles_without))), st["meta"]))

    # --- driver records -------------------------------------------------------------------------------
    story += [PageBreak(), Paragraph("7. Driver records (status today)", st["h1"])]
    recs = await records_for(session, drivers)
    word = {"expired": "Expired", "overdue": "Overdue", "due_soon": "Due soon", "missing": "Not recorded", "ok": "OK", "not_applicable": "n/a"}

    def cell(item, value):
        return _p(st, value or word.get(item["status"], ""), BAD if item["status"] in ("expired", "overdue", "missing") else None)

    story.append(_table(st, ["Driver", "Licence expiry", "Licence last checked", "DQC expiry", "CPC hours (5 yrs)", "Tacho card", "Medical", "ADR"], [
        [r["name"], cell(r["items"]["licence"], _d(r["items"]["licence"]["date"])),
         cell(r["items"]["licence_check"], _d(r["items"]["licence_check"]["last"]) + (f" (next {_d(r['items']['licence_check']['next_due'])})" if r["items"]["licence_check"]["next_due"] else "")),
         cell(r["items"]["dqc"], _d(r["items"]["dqc"]["date"])),
         cell(r["items"]["cpc_training"], f"{r['items']['cpc_training']['hours']} / 35"),
         cell(r["items"]["tacho_card"], _d(r["items"]["tacho_card"]["date"])),
         cell(r["items"]["medical"], _d(r["items"]["medical"]["date"])), cell(r["items"]["adr"], _d(r["items"]["adr"]["date"]))]
        for r in recs], [48 * mm, 28 * mm, 45 * mm, 26 * mm, 26 * mm, 26 * mm, 24 * mm, 24 * mm])
        if recs else Paragraph("No drivers on record.", st["empty"]))

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(12 * mm, 7 * mm, f"{company} · inspection pack {_d(start)}–{_d(end)}")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title="Compliance inspection pack", author=company)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
