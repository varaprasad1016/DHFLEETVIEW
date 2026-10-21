"""Proper PDF reports from the fleet's own GPS.

The platforms this replaces print a bare grid: every column the database has,
the vehicle's name repeated on all forty rows, addresses folded into a column
two words wide, and no total anywhere. A transport manager reads the top of a
report for the answer and the table only when something looks wrong, so that is
how this is laid out - the figures that answer the question first, the rows
underneath, and the page says which GPS it came from, because a report built on
a camera's position is not the same evidence as one built on a tracker.

Positions come from DH FleetView, which already prefers a vehicle's tracker and
falls back to its camera; this only has to say which one was used.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Table, TableStyle)

UK = ZoneInfo("Europe/London")

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
RULE = colors.HexColor("#e2e8f0")
BAND = colors.HexColor("#f1f5f9")
PLATE = colors.HexColor("#ffd400")
GOOD = colors.HexColor("#15803d")
WARN = colors.HexColor("#b45309")

PAGE = landscape(A4)
MARGIN = 14 * mm


def _style(name, size, colour=INK, bold=False, leading=None, align=None):
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading or size + 2,
        textColor=colour,
        alignment=align if align is not None else 0,
    )


CELL = _style("cell", 7.4, INK, leading=9)
CELL_MUTED = _style("cellMuted", 7.0, MUTED, leading=8.6)
CELL_NUM = _style("cellNum", 7.4, INK, leading=9, align=TA_RIGHT)
HEAD_CELL = _style("headCell", 6.6, colors.white, bold=True, leading=8)


# --- turning Traccar's units into the ones a UK yard uses -------------------

def miles(metres) -> float:
    return (metres or 0) / 1609.344


def mph(knots) -> float:
    return (knots or 0) * 1.150779


def hours_minutes(milliseconds) -> str:
    total = int((milliseconds or 0) / 1000)
    h, m = total // 3600, (total % 3600) // 60
    if h and m:
        return f"{h}h {m:02d}m"
    if h:
        return f"{h}h"
    return f"{m}m" if m else f"{total}s"


def when(value, with_date=False) -> str:
    if not value:
        return "-"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UK)
    except ValueError:
        return str(value)
    return moment.strftime("%d %b %H:%M:%S" if with_date else "%H:%M:%S")


def place(address, latitude, longitude) -> str:
    """An address if the geocoder found one, otherwise the coordinate itself."""
    if address:
        text = str(address).replace(", England", "").replace(", United Kingdom", "")
        return text
    if latitude is None or longitude is None:
        return "-"
    return f"{latitude:.5f}, {longitude:.5f}"


@dataclass
class Report:
    """Everything the page needs, worked out before any drawing starts."""

    kind: str
    title: str
    brand: str
    period_from: datetime
    period_to: datetime
    vehicles: list[dict]
    rows: list[dict]
    source: str
    source_detail: str
    figures: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


# --- the page furniture ------------------------------------------------------

class _Doc(BaseDocTemplate):
    def __init__(self, buffer, report: Report):
        super().__init__(buffer, pagesize=PAGE,
                         leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN + 30 * mm, bottomMargin=MARGIN + 8 * mm,
                         title=f"{report.title} — {report.brand}", author=report.brand)
        self.report = report
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=self._furniture)])

    def _furniture(self, canvas, _doc):
        report = self.report
        width, height = PAGE
        canvas.saveState()

        # Masthead: the report, the vehicle, the period, and where the fix came
        # from - the four things someone checks before reading a single row.
        canvas.setFillColor(INK)
        canvas.rect(0, height - 26 * mm, width, 26 * mm, stroke=0, fill=1)

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(MARGIN, height - 13 * mm, report.title)

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#cbd5e1"))
        period = (f"{report.period_from.strftime('%a %d %b %Y, %H:%M')}"
                  f"  to  {report.period_to.strftime('%a %d %b %Y, %H:%M')}")
        canvas.drawString(MARGIN, height - 19 * mm, period)

        # The registration, drawn as the plate it is.
        if report.vehicles:
            label = report.vehicles[0].get("name", "")
            extra = len(report.vehicles) - 1
            text = f"{label}  +{extra} more" if extra > 0 else label
            canvas.setFont("Helvetica-Bold", 11)
            plate_width = canvas.stringWidth(text, "Helvetica-Bold", 11) + 12
            x = width - MARGIN - plate_width
            canvas.setFillColor(PLATE)
            canvas.roundRect(x, height - 15 * mm, plate_width, 7.5 * mm, 1.6, stroke=0, fill=1)
            canvas.setFillColor(INK)
            canvas.drawString(x + 6, height - 13 * mm, text)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#cbd5e1"))
        canvas.drawRightString(width - MARGIN, height - 19 * mm, f"Position source: {report.source}")
        if report.source_detail:
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#94a3b8"))
            canvas.drawRightString(width - MARGIN, height - 22.5 * mm, report.source_detail)

        # The answer band: totals, before any row of the table.
        if report.figures:
            top = height - 26 * mm
            canvas.setFillColor(BAND)
            canvas.rect(0, top - 16 * mm, width, 16 * mm, stroke=0, fill=1)
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.5)
            canvas.line(0, top - 16 * mm, width, top - 16 * mm)
            step = (width - 2 * MARGIN) / len(report.figures)
            for index, (label, value) in enumerate(report.figures):
                x = MARGIN + index * step
                canvas.setFillColor(MUTED)
                canvas.setFont("Helvetica", 6.4)
                canvas.drawString(x, top - 6 * mm, label.upper())
                canvas.setFillColor(INK)
                canvas.setFont("Helvetica-Bold", 13)
                canvas.drawString(x, top - 12.5 * mm, value)

        # Footer.
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 12 * mm, width - MARGIN, 12 * mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 8 * mm, f"{report.brand}   /   generated "
                          f"{datetime.now(UK).strftime('%d %b %Y %H:%M')}")
        if report.note:
            canvas.drawCentredString(width / 2, 8 * mm, report.note)
        canvas.drawRightString(width - MARGIN, 8 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()


def _table(columns, rows, widths):
    """One table, striped, with the header repeated on every page."""
    data = [[Paragraph(c.upper(), HEAD_CELL) for c in columns]] + rows
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]
    table.setStyle(TableStyle(style))
    return table


def render(report: Report) -> bytes:
    buffer = io.BytesIO()
    doc = _Doc(buffer, report)
    body = []

    if not report.rows:
        body.append(Paragraph(
            "Nothing was recorded for this vehicle in this period.", _style("empty", 10, MUTED)))
    else:
        columns, widths, rows = BUILDERS[report.kind](report, doc.width)
        body.append(_table(columns, rows, widths))

    doc.build(body)
    return buffer.getvalue()


# --- one builder per report --------------------------------------------------

def _trips(report: Report, width):
    columns = ["#", "Start", "From", "End", "To", "Distance", "Driving", "Max", "Average", "Driver"]
    shares = [0.030, 0.075, 0.215, 0.075, 0.215, 0.070, 0.070, 0.055, 0.060, 0.135]
    rows = []
    multi = len({r.get("deviceId") for r in report.rows}) > 1
    if multi:
        columns.insert(1, "Vehicle")
        shares = [0.030, 0.085] + [s * 0.915 for s in shares[1:]]
    for index, trip in enumerate(report.rows, start=1):
        cells = [Paragraph(str(index), CELL_MUTED)]
        if multi:
            cells.append(Paragraph(str(trip.get("deviceName") or ""), CELL))
        cells += [
            Paragraph(when(trip.get("startTime")), CELL),
            Paragraph(place(trip.get("startAddress"), trip.get("startLat"), trip.get("startLon")), CELL_MUTED),
            Paragraph(when(trip.get("endTime")), CELL),
            Paragraph(place(trip.get("endAddress"), trip.get("endLat"), trip.get("endLon")), CELL_MUTED),
            Paragraph(f"{miles(trip.get('distance')):.1f} mi", CELL_NUM),
            Paragraph(hours_minutes(trip.get("duration")), CELL_NUM),
            Paragraph(f"{mph(trip.get('maxSpeed')):.0f}", CELL_NUM),
            Paragraph(f"{mph(trip.get('averageSpeed')):.0f}", CELL_NUM),
            Paragraph(str(trip.get("driverName") or "-"), CELL_MUTED),
        ]
        rows.append(cells)
    return columns, [width * s for s in shares], rows


def _stops(report: Report, width):
    columns = ["#", "Arrived", "Left", "Stopped for", "Where", "Engine hours"]
    shares = [0.035, 0.105, 0.105, 0.105, 0.545, 0.105]
    rows = []
    for index, stop in enumerate(report.rows, start=1):
        rows.append([
            Paragraph(str(index), CELL_MUTED),
            Paragraph(when(stop.get("startTime"), with_date=True), CELL),
            Paragraph(when(stop.get("endTime"), with_date=True), CELL),
            Paragraph(hours_minutes(stop.get("duration")), CELL_NUM),
            Paragraph(place(stop.get("address"), stop.get("latitude"), stop.get("longitude")), CELL_MUTED),
            Paragraph(hours_minutes(stop.get("engineHours")), CELL_NUM),
        ])
    return columns, [width * s for s in shares], rows


def _summary(report: Report, width):
    columns = ["Vehicle", "Distance", "Driving", "Max speed", "Average speed",
               "Odometer start", "Odometer end", "Engine hours"]
    shares = [0.22, 0.10, 0.10, 0.10, 0.12, 0.12, 0.12, 0.10]
    rows = []
    for line in report.rows:
        rows.append([
            Paragraph(str(line.get("deviceName") or ""), CELL),
            Paragraph(f"{miles(line.get('distance')):.1f} mi", CELL_NUM),
            Paragraph(hours_minutes(line.get("engineHours")), CELL_NUM),
            Paragraph(f"{mph(line.get('maxSpeed')):.0f} mph", CELL_NUM),
            Paragraph(f"{mph(line.get('averageSpeed')):.0f} mph", CELL_NUM),
            Paragraph(f"{miles(line.get('startOdometer')):,.0f} mi", CELL_NUM),
            Paragraph(f"{miles(line.get('endOdometer')):,.0f} mi", CELL_NUM),
            Paragraph(hours_minutes(line.get("engineHours")), CELL_NUM),
        ])
    return columns, [width * s for s in shares], rows


def _events(report: Report, width):
    columns = ["#", "When", "Vehicle", "Event", "Where"]
    shares = [0.035, 0.13, 0.17, 0.22, 0.445]
    rows = []
    for index, event in enumerate(report.rows, start=1):
        rows.append([
            Paragraph(str(index), CELL_MUTED),
            Paragraph(when(event.get("eventTime") or event.get("serverTime"), with_date=True), CELL),
            Paragraph(str(event.get("deviceName") or ""), CELL),
            Paragraph(str(event.get("type") or "").replace("device", "").replace("Alarm", " alarm").strip().title(), CELL),
            Paragraph(place(event.get("address"), event.get("latitude"), event.get("longitude")), CELL_MUTED),
        ])
    return columns, [width * s for s in shares], rows


BUILDERS = {"trips": _trips, "stops": _stops, "summary": _summary, "events": _events}


# --- the figures that go in the band ----------------------------------------

def figures_for(kind: str, rows: list[dict]) -> list[tuple[str, str]]:
    if kind == "trips":
        # A vehicle whose history mixes a tracker's odometer with a camera's can
        # show a trip running backwards. Those are not distances anyone drove,
        # so they are left out of the total rather than subtracted from it; the
        # count of them is what tells you the history needs looking at.
        lengths = [miles(r.get("distance")) for r in rows]
        sound = [d for d in lengths if d >= 0]
        distance = sum(sound)
        driving = sum(r.get("duration") or 0 for r in rows)
        fastest = max((mph(r.get("maxSpeed")) for r in rows), default=0)
        longest = max(sound, default=0)
        figures = [
            ("Trips", f"{len(rows)}"),
            ("Distance", f"{distance:,.1f} mi"),
            ("Driving time", hours_minutes(driving)),
            ("Longest trip", f"{longest:,.1f} mi"),
            ("Fastest", f"{fastest:.0f} mph"),
        ]
        if len(sound) != len(lengths):
            figures.append(("Discounted", f"{len(lengths) - len(sound)} trips"))
        return figures
    if kind == "stops":
        stopped = sum(r.get("duration") or 0 for r in rows)
        longest = max((r.get("duration") or 0 for r in rows), default=0)
        return [
            ("Stops", f"{len(rows)}"),
            ("Stopped for", hours_minutes(stopped)),
            ("Longest stop", hours_minutes(longest)),
        ]
    if kind == "summary":
        distance = sum(miles(r.get("distance")) for r in rows)
        engine = sum(r.get("engineHours") or 0 for r in rows)
        figures = [("Vehicles", f"{len(rows)}"), ("Distance", f"{distance:,.1f} mi")]
        if engine:
            figures.append(("Engine hours", hours_minutes(engine)))
        return figures
    if kind == "events":
        kinds = len({r.get("type") for r in rows})
        return [("Events", f"{len(rows)}"), ("Kinds", f"{kinds}")]
    return []
