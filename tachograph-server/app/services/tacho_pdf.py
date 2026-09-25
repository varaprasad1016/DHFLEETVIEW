"""Render a weekly driver report to PDF.

The layout follows the report an operator already knows: one page per week, a
row per day, then the working-time breaches, the drivers' hours breaches, the
faults the tachograph recorded, and the two signature lines that make the page
evidence of a driver debrief rather than just a printout.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from app.services.tacho_report import hhmm

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
BAND = colors.HexColor("#f3f4f6")
BAD = colors.HexColor("#b91c1c")
WARN = colors.HexColor("#b45309")

# Widths add up to the printable width of a landscape A4 page less the margins,
# so nothing has to wrap.
# Shift duty and WTD active hours are two different figures - the first counts
# availability, the second does not - so they get a column each and are never
# merged into one "WTD" column that means whichever the reader assumes.
COLUMNS = [
    ("Date", 46), ("Reg", 54), ("Finish<br/>odo", 46), ("Start<br/>odo", 46),
    ("Dist<br/>(km)", 32), ("Start<br/>duty", 34), ("Drive<br/>start", 34),
    ("End<br/>duty", 34), ("Daily<br/>rest", 38), ("Total<br/>drive", 38),
    ("Total<br/>work", 38), ("Total<br/>POA", 38), ("Total<br/>break", 38),
    ("Total<br/>shift", 40), ("Shift duty<br/>(inc. POA)", 48),
    ("WTD active<br/>(excl. POA)", 50), ("Fort<br/>drive", 40),
    ("Prev<br/>rest", 38), ("Rule", 40),
]
FINDING_WIDTHS = [56, 32, 58, 616]


def _styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold",
                                fontSize=13, leading=15, textColor=INK),
        "meta": ParagraphStyle("m", parent=base, fontSize=7.5, leading=10, textColor=MUTED),
        "head": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold",
                               fontSize=8.5, leading=10, textColor=INK,
                               spaceBefore=5, spaceAfter=1),
        "cell": ParagraphStyle("c", parent=base, fontSize=6.6, leading=8),
        "note": ParagraphStyle("n", parent=base, fontSize=7, leading=8.6, textColor=INK),
        "empty": ParagraphStyle("e", parent=base, fontSize=7, leading=8.6,
                                textColor=MUTED, fontName="Helvetica-Oblique"),
    }


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%a %d/%m}"


def _odo(value: int | None) -> str:
    return f"{value:,}" if value else ""


def _day_cells(row: dict) -> list[str]:
    if row["no_data"]:
        return [_fmt_date(row["date"]), "No data"] + [""] * (len(COLUMNS) - 2)
    if row["rest_day"]:
        cells = [_fmt_date(row["date"]), "Rest Day"] + [""] * (len(COLUMNS) - 2)
        cells[15] = hhmm(row["fortnight_drive"])
        return cells
    return [
        _fmt_date(row["date"]), row["registration"],
        _odo(row["odometer_end"]), _odo(row["odometer_start"]),
        str(row["distance"]) if row["distance"] else "",
        row["start_duty"], row["drive_start"], row["end_duty"],
        hhmm(row["daily_rest"]), hhmm(row["drive"]), hhmm(row["work"]),
        hhmm(row["poa"]), hhmm(row["break"]), hhmm(row["shift"]),
        hhmm(row.get("shift_duty", row.get("wtd"))), hhmm(row.get("wtd_active")),
        hhmm(row["fortnight_drive"]), hhmm(row["previous_rest"]), row["rule"],
    ]


def _totals_cells(totals: dict) -> list[str]:
    cells = ["Week's total"] + [""] * (len(COLUMNS) - 1)
    cells[4] = str(totals.get("distance") or 0)
    for index, key in ((8, "daily_rest"), (9, "drive"), (10, "work"), (11, "poa"),
                       (12, "break"), (13, "shift"), (14, "shift_duty"),
                       (15, "wtd_active")):
        cells[index] = hhmm(totals.get(key) or 0)
    return cells


def _day_table(week: dict, st: dict) -> Table:
    header = [Paragraph(f"<b>{name}</b>", st["cell"]) for name, _ in COLUMNS]
    body = [_day_cells(row) for row in week["days"]]
    data = [header] + body + [_totals_cells(week["totals"])]
    table = Table(data, colWidths=[w for _, w in COLUMNS], repeatRows=1)

    style = [
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.6),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, row in enumerate(week["days"], start=1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), BAND))
        if row["no_data"]:
            style.append(("TEXTCOLOR", (0, i), (-1, i), MUTED))
    table.setStyle(TableStyle(style))
    return table


def _review_text(review: dict | None) -> str:
    """Driver sign-off and office debrief, as a line under the infringement."""
    if not review:
        return ""
    parts = []
    if review.get("driver_signed_at"):
        signed = _fmt_date(review["driver_signed_at"][:10])
        parts.append(f"Driver signed {signed}" + (f' ("{escape(review["driver_comment"])}")' if review.get("driver_comment") else ""))
    if review.get("debrief_action_label"):
        by = f" by {escape(review['debriefed_by'])}" if review.get("debriefed_by") else ""
        on = f" on {_fmt_date(review['debriefed_at'][:10])}" if review.get("debriefed_at") else ""
        notes = f" — {escape(review['debrief_notes'])}" if review.get("debrief_notes") else ""
        parts.append(f"Debrief: {escape(review['debrief_action_label'])}{by}{on}{notes}")
    return ('<br/><font color="#374151">' + " · ".join(parts) + "</font>") if parts else ""


def _findings(title: str, items: list[dict], st: dict, kind: str) -> list:
    out = [Paragraph(title, st["head"])]
    if not items:
        out.append(Paragraph("No messages found", st["empty"]))
        return out
    rows = []
    for item in items:
        if kind == "fault":
            text = f"{item['name']}" + (f" ({item['registration']})"
                                        if item.get("registration") else "")
            rows.append([_fmt_date(item["date"]), item["time"], "", Paragraph(text, st["note"])])
            continue
        severity = item["severity"].replace("_", " ")
        colour = BAD if item["severity"] == "very_serious" else (
            WARN if item["severity"] == "serious" else MUTED)
        rows.append([
            _fmt_date(item["date"]), item["time"],
            Paragraph(f'<font color="#{colour.hexval()[2:]}"><b>{severity}</b></font>',
                      st["cell"]),
            Paragraph(f"<b>{item['title']}.</b> {item['detail']}{_review_text(item.get('review'))}", st["note"]),
        ])
    table = Table(rows, colWidths=FINDING_WIDTHS)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TEXTCOLOR", (0, 0), (1, -1), MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(table)
    return out


def _signatures(st: dict) -> Table:
    line = ParagraphStyle("sig", parent=st["meta"], textColor=MUTED)
    rows = [
        [Paragraph("Signature of driver", line), Paragraph("Place and date", line)],
        [Paragraph("Signature of responsible person", line), Paragraph("Place and date", line)],
    ]
    table = Table(rows, colWidths=[420, 360], rowHeights=[26, 26])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


TIMELINE_COLORS = {
    "DRIVE": colors.HexColor("#ef1717"),
    "WORK": colors.HexColor("#1d9b3a"),
    "AVAILABLE": colors.HexColor("#f1cf35"),
    "REST": colors.HexColor("#3f46c9"),
}
TIMELINE_BG = colors.HexColor("#fffed2")
TIMELINE_GRID = colors.HexColor("#4b5563")
LOCAL_TZ = ZoneInfo("Europe/London")


def _timeline_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(LOCAL_TZ)


def _timeline_days(rows: list[dict]) -> dict[date, list[dict]]:
    days: dict[date, list[dict]] = {}
    for row in rows:
        start = _timeline_dt(row["start"])
        end = _timeline_dt(row["end"])
        while end > start:
            day_end = datetime(start.year, start.month, start.day, tzinfo=LOCAL_TZ) + timedelta(days=1)
            clipped_end = min(end, day_end)
            clipped = dict(row)
            clipped["start"], clipped["end"] = start.isoformat(), clipped_end.isoformat()
            days.setdefault(start.date(), []).append(clipped)
            start = clipped_end
    return dict(sorted(days.items()))


def _timeline_lanes(rows: list[dict]) -> list[tuple[str, str, list[dict]]]:
    lanes: dict[str, list[dict]] = {}
    for row in rows:
        driver = row.get("driver_ref") or "Driver activity"
        lanes.setdefault(driver, []).append(row)
    return [
        (driver, ", ".join(dict.fromkeys(row.get("vehicle_ref") for row in lane if row.get("vehicle_ref")))
         or "Registration unavailable", lane)
        for driver, lane in lanes.items()
    ] or [("Driver activity", "Registration unavailable", [])]


def _timeline_block(c: pdf_canvas.Canvas, day: date, rows: list[dict], top: float,
                    page_width: float) -> float:
    lanes = _timeline_lanes(rows)
    block_height = 52 + 60 * len(lanes)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(32, top, day.strftime("%A %d/%m/%Y"))
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawRightString(page_width - 32, top, "Daily values 00:00 to 24:00 local time")

    # Reserve a complete row for the legend before the first chart starts.
    legend_x = 32
    legend_y = top - 19
    c.setFont("Helvetica", 7)
    for name in ("DRIVE", "WORK", "AVAILABLE", "REST"):
        c.setFillColor(TIMELINE_COLORS[name])
        c.rect(legend_x, legend_y - 2, 9, 9, fill=1, stroke=0)
        c.setFillColor(INK)
        c.drawString(legend_x + 13, legend_y, name.title())
        legend_x += 78 if name != "AVAILABLE" else 99

    left, right = 56, page_width - 32
    chart_width = right - left
    lane_top = top - 55
    for lane_index, (driver, registration, lane_rows) in enumerate(lanes):
        y = lane_top - lane_index * 60
        c.setFillColor(TIMELINE_BG)
        c.rect(left, y - 3, chart_width, 27, fill=1, stroke=0)
        c.setStrokeColor(TIMELINE_GRID)
        c.setLineWidth(0.35)
        for hour in range(25):
            x = left + chart_width * hour / 24
            c.line(x, y - 3, x, y + 24)
            if hour < 24:
                c.setFillColor(INK)
                c.setFont("Helvetica", 6)
                c.drawCentredString(x + chart_width / 48, y - 16, str(hour))
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(2, y + 13, driver[:22])
        c.setFont("Helvetica", 6)
        c.drawString(2, y + 3, registration[:25])

        day_start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
        day_end = day_start + timedelta(days=1)
        for row in lane_rows:
            start = max(_timeline_dt(row["start"]), day_start)
            end = min(_timeline_dt(row["end"]), day_end)
            if end <= start:
                continue
            start_fraction = (start - day_start).total_seconds() / (day_end - day_start).total_seconds()
            end_fraction = (end - day_start).total_seconds() / (day_end - day_start).total_seconds()
            x = left + chart_width * start_fraction
            width = max(1, chart_width * (end_fraction - start_fraction))
            c.setFillColor(TIMELINE_COLORS.get(row.get("activity", "").upper(), MUTED))
            c.rect(x, y, width, 20, fill=1, stroke=0)
            if width > 24:
                c.setFillColor(colors.white if row.get("activity", "").upper() in ("DRIVE", "REST") else INK)
                c.setFont("Helvetica-Bold", 5.5)
                c.drawCentredString(x + width / 2, y + 7, row.get("activity", "").title())
    return block_height


def render_timeline(rows: list[dict], driver_ref: str | None = None,
                    generated: datetime | None = None) -> bytes:
    """Render canonical activities as daily 24-hour tachograph charts."""
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    c = pdf_canvas.Canvas(buffer, pagesize=(page_width, page_height),
                          title="Tachograph activity timeline")
    days = _timeline_days(rows)
    stamp = (generated or datetime.now()).strftime("%d/%m/%Y %H:%M")

    def header() -> None:
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(32, page_height - 32, "Tachograph activity timeline")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawRightString(page_width - 32, page_height - 31, f"Generated {stamp}")
        c.drawString(32, page_height - 47, f"Driver: {driver_ref or '—'}")
        # Say which days these are. A card downloaded today can hold nothing
        # newer than months ago, and a driver looking at their own timeline
        # should not have to work out from the day headings that they are
        # reading June rather than this week.
        if days:
            first, last = min(days), max(days)
            covers = (first.strftime("%d/%m/%Y") if first == last
                      else f"{first:%d/%m/%Y} to {last:%d/%m/%Y}")
            c.drawRightString(page_width - 32, page_height - 47, f"Covering {covers}")
        c.line(32, page_height - 55, page_width - 32, page_height - 55)

    header()
    y = page_height - 78
    if not days:
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(32, y, "No activity in the selected period.")
    else:
        for day, day_rows in days.items():
            height = 80 + 60 * len(_timeline_lanes(day_rows))
            if y - height < 38:
                c.showPage()
                header()
                y = page_height - 78
            _timeline_block(c, day, day_rows, y, page_width)
            y -= height + 17
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.5)
    c.drawString(32, 18, "Times shown in Europe/London. Activity values are taken from driver-card downloads.")
    c.save()
    return buffer.getvalue()


def render(report: dict, generated: datetime | None = None) -> bytes:
    st = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=12 * mm,
        title="Driver weekly report",
        author=report.get("driver", {}).get("name") or "")

    driver = report.get("driver", {})
    period = report.get("period", {})
    stamp = (generated or datetime.now()).strftime("%d/%m/%Y %H:%M")
    who = driver.get("name") or driver.get("ref") or "Unknown driver"
    card = driver.get("card_number")

    company = report.get("company_name")
    story: list = []
    for index, week in enumerate(report.get("weeks", [])):
        if index:
            story.append(PageBreak())
        if company:
            story.append(Paragraph(company, st["title"]))
        story.append(Paragraph("Driver weekly report", st["title"]))
        story.append(Paragraph(
            f"Generated {stamp}. Period {_fmt_date(period['from'])} to "
            f"{_fmt_date(period['to'])}, times shown in {period.get('timezone', 'UTC')}.",
            st["meta"]))
        story.append(Spacer(1, 5))
        story.append(Paragraph(
            f"<b>{who}</b>" + (f", card {card}" if card else "") +
            f". Week {_fmt_date(week['start'])} to {_fmt_date(week['end'])}.",
            st["note"]))
        story.append(Spacer(1, 4))
        story.append(_day_table(week, st))
        story += _findings("Working time infringements",
                           week["working_time_infringements"], st, "infringement")
        story += _findings("Infringements", week["infringements"], st, "infringement")
        story += _findings("Faults", week["faults"], st, "fault")
        story.append(Spacer(1, 7))
        story.append(Paragraph(
            "The driver confirms being informed of the infringements listed above, and that "
            "they were instructed to observe the driving times and rest periods required by law.",
            st["meta"]))
        story.append(Spacer(1, 6))
        story.append(KeepTogether(_signatures(st)))

    if not story:
        story = [Paragraph("Driver weekly report", st["title"]),
                 Paragraph("No data in the selected period.", st["empty"])]
    doc.build(story)
    return buffer.getvalue()
