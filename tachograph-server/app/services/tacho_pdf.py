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

    story: list = []
    for index, week in enumerate(report.get("weeks", [])):
        if index:
            story.append(PageBreak())
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
