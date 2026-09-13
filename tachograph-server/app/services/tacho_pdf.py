"""Render a weekly driver report to PDF.

The layout follows the report an operator already knows: one page per week, a
row per day, then the working-time breaches, the drivers' hours breaches, the
faults the tachograph recorded, and the two signature lines that make the page
evidence of a driver debrief rather than just a printout.
"""

from __future__ import annotations

import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from app.services.tacho_report import hhmm

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
BAND = colors.HexColor("#f3f4f6")
BAD = colors.HexColor("#b91c1c")
WARN = colors.HexColor("#b45309")

# Widths add up to the printable width of a landscape A4 page less the margins,
# so nothing has to wrap.
COLUMNS = [
    ("Date", 50), ("Reg", 62), ("Finish<br/>odo", 50), ("Start<br/>odo", 50),
    ("Dist<br/>(km)", 34), ("Start<br/>duty", 36), ("Drive<br/>start", 36),
    ("End<br/>duty", 36), ("Daily<br/>rest", 40), ("Total<br/>drive", 40),
    ("Total<br/>work", 40), ("Total<br/>POA", 40), ("Total<br/>break", 40),
    ("Total<br/>shift", 42), ("Total<br/>WTD", 40), ("Fort<br/>drive", 42),
    ("Prev<br/>rest", 40), ("Rule", 44),
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


def _timeline_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%A %d/%m/%Y")


class DriverTimeline(Flowable):
    """Draw one compact driver-card timeline in the tachograph printout."""

    COLORS = {
        "drive": colors.HexColor("#1010f5"),
        "work": colors.HexColor("#38761d"),
        "available": colors.HexColor("#f1c232"),
        "rest": colors.HexColor("#777777"),
    }

    def __init__(self, row: dict, driver: dict, width: float = 774, height: float = 72):
        super().__init__()
        self.row = row
        self.driver = driver
        self.width = width
        self.height = height

    def wrap(self, avail_width, avail_height):
        self.width = min(self.width, avail_width)
        return self.width, self.height

    def _legend_icon(self, kind: str, x: float, y: float):
        c = self.canv
        colour = self.COLORS[kind]
        c.setStrokeColor(colour)
        c.setFillColor(colour)
        c.setLineWidth(1.3)
        if kind in ("drive", "rest"):
            c.circle(x + 5, y + 4, 4, stroke=1, fill=0)
            c.line(x + 2, y + 4, x + 8, y + 4)
            if kind == "rest":
                c.line(x + 2, y + 1, x + 8, y + 7)
        elif kind == "work":
            c.line(x + 1, y + 1, x + 9, y + 9)
            c.line(x + 9, y + 1, x + 1, y + 9)
        else:
            c.rect(x + 1, y + 1, 8, 8, stroke=1, fill=0)

    def draw(self):
        c = self.canv
        row = self.row
        left = 34
        track_left = left + 4
        track_width = self.width - track_left - 2
        header_y = self.height - 13
        ruler_top = self.height - 29
        band_top = ruler_top - 10

        c.setStrokeColor(LINE)
        c.setLineWidth(.45)
        c.line(0, self.height - 1, self.width, self.height - 1)
        c.line(0, self.height - 17, self.width, self.height - 17)
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(BAD)
        c.drawString(2, header_y, _timeline_label(row["date"]))
        c.setFont("Helvetica", 7.5)
        c.setFillColor(INK)
        c.drawString(174, header_y, "Daily values 0:00 To 24:00 O'clock")

        totals = row.get("timeline_totals") or {}
        legend = ("drive", "work", "available", "rest")
        legend_x = 430
        for kind in legend:
            self._legend_icon(kind, legend_x, header_y - 4)
            c.setFillColor(INK)
            c.setFont("Helvetica", 7.5)
            c.drawString(legend_x + 14, header_y, hhmm(totals.get(kind) or 0))
            legend_x += 54

        # Driver-card marker and the driver's registration, rather than a lane
        # per vehicle-unit file.
        c.setFillColor(colors.HexColor("#a5a5a5"))
        c.rect(2, ruler_top - 3, 22, 13, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.circle(8, ruler_top + 4, 2.6, stroke=0, fill=1)
        c.rect(6, ruler_top - 1, 5, 3, stroke=0, fill=1)
        c.setStrokeColor(colors.white)
        c.setLineWidth(.7)
        c.line(14, ruler_top + 5, 20, ruler_top + 5)
        c.line(14, ruler_top + 2, 20, ruler_top + 2)
        c.setStrokeColor(INK)
        c.setLineWidth(1)
        c.line(9, ruler_top - 3, 9, ruler_top - 18)
        c.setFillColor(INK)
        c.setFont("Helvetica", 6.5)
        name = self.driver.get("name") or self.driver.get("ref") or "Driver"
        registration = row.get("registration") or ""
        if registration.strip().lower() in {"registration unavailable", "unknown", "n/a", "none"}:
            registration = ""
        c.drawString(0, ruler_top - 27, name[:18])
        if registration:
            c.setFillColor(BAD)
            c.drawString(0, ruler_top - 35, registration[:18])

        # A thin neutral reference line keeps an empty/rest-only day visually
        # quiet. Only recorded driver-card states are painted over it below.
        c.setFillColor(colors.HexColor("#777777"))
        c.rect(track_left, band_top, track_width, .8, stroke=0, fill=1)

        # Activity segments are overlaid on the baseline using the exact same
        # 00:00–24:00 minute coordinates as the browser timeline. Rest is
        # intentionally omitted so a full-day rest does not become a solid bar.
        for segment in row.get("timeline") or []:
            if segment["type"] not in ("drive", "work", "available"):
                continue
            x = track_left + track_width * segment["start"] / 1440
            w = track_width * (segment["end"] - segment["start"]) / 1440
            c.setFillColor(self.COLORS.get(segment["type"], self.COLORS["rest"]))
            c.rect(x, band_top - 1, max(w, .35), 8, stroke=0, fill=1)

        c.setStrokeColor(INK)
        c.setLineWidth(.55)
        for tick in range(49):
            x = track_left + track_width * tick / 48
            tick_height = 14 if tick % 2 == 0 else (9 if tick % 4 == 1 else 5)
            c.line(x, band_top + 9, x, band_top + 9 + tick_height)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(INK)
        for hour in range(25):
            x = track_left + track_width * hour / 24
            text = str(hour)
            offset = 0 if hour == 0 else (-c.stringWidth(text, "Helvetica", 6.5) if hour == 24 else -c.stringWidth(text, "Helvetica", 6.5) / 2)
            c.drawString(x + offset, band_top - 29, text)


def _timeline_table(week: dict, driver: dict, st: dict) -> list:
    out = [Paragraph("Driver timeline", st["head"])]
    for row in week.get("days", []):
        out.append(DriverTimeline(row, driver))
    return out


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
        hhmm(row["poa"]), hhmm(row["break"]), hhmm(row["shift"]), hhmm(row["wtd"]),
        hhmm(row["fortnight_drive"]), hhmm(row["previous_rest"]), row["rule"],
    ]


def _totals_cells(totals: dict) -> list[str]:
    cells = ["Week's total"] + [""] * (len(COLUMNS) - 1)
    cells[4] = str(totals.get("distance") or 0)
    for index, key in ((8, "daily_rest"), (9, "drive"), (10, "work"), (11, "poa"),
                       (12, "break"), (13, "shift"), (14, "wtd")):
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
            Paragraph(f"<b>{item['title']}.</b> {item['detail']}", st["note"]),
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


def render(report: dict, generated: datetime | None = None) -> bytes:
    """Return the report as PDF bytes."""
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

    company = report.get("company_name") or "DH FleetView"
    story: list = []
    for index, week in enumerate(report.get("weeks", [])):
        if index:
            story.append(PageBreak())
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
        story += _timeline_table(week, driver, st)
        story.append(Spacer(1, 5))
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
