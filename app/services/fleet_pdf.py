"""Render the fleet-level tachograph reports to PDF.

Four reports share one renderer because they share one shape: a banded table
an operator reads top-down, worst first, with a legend that says what the
colours mean. Keeping them in one place is what stops the download reports and
the performance summary drifting into three slightly different house styles.

The colour is not decoration. On the two download reports it is the whole
finding - a transport manager scanning for red is the intended use - so the
band is also printed as a word in the days column, because a page that has
been photocopied, faxed to a solicitor or printed on the depot's mono laser
still has to carry it.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

LOCAL_TZ = ZoneInfo("Europe/London")

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
HEAD_BG = colors.HexColor("#f3f4f6")

BANDS = {
    "green": (colors.HexColor("#dcfce7"), colors.HexColor("#166534")),
    "amber": (colors.HexColor("#fef3c7"), colors.HexColor("#92400e")),
    "red": (colors.HexColor("#fee2e2"), colors.HexColor("#991b1b")),
}


def _styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold",
                                fontSize=13, leading=15, textColor=INK),
        "meta": ParagraphStyle("m", parent=base, fontSize=7.5, leading=10, textColor=MUTED),
        "head": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold",
                               fontSize=6.8, leading=8.2, textColor=INK),
        "cell": ParagraphStyle("c", parent=base, fontSize=6.8, leading=8.2, textColor=INK),
        "empty": ParagraphStyle("e", parent=base, fontSize=8, leading=10,
                                textColor=MUTED, fontName="Helvetica-Oblique"),
    }


def _fmt(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _d(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def render_table(title: str, columns: list[tuple[str, float]], rows: list[dict],
                 company: str | None = None, filters: str | None = None,
                 legend: list[tuple[str, str]] | None = None,
                 generated: datetime | None = None,
                 empty_note: str = "Nothing to report.") -> bytes:
    """One banded table. `rows` are {"cells": [...], "band": "green"|...}."""
    st = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=12 * mm,
        title=title, author=company or "")

    stamp = (generated or datetime.now(LOCAL_TZ)).strftime("%d/%m/%Y %H:%M")
    story: list = []
    if company:
        story.append(Paragraph(escape(company), st["title"]))
    story.append(Paragraph(escape(title), st["title"]))
    story.append(Paragraph(f"Generated {stamp}.", st["meta"]))
    if filters:
        story.append(Paragraph(escape(filters), st["meta"]))
    story.append(Spacer(1, 6))

    if not rows:
        story.append(Paragraph(escape(empty_note), st["empty"]))
    else:
        data = [[Paragraph(label, st["head"]) for label, _ in columns]]
        for row in rows:
            data.append([Paragraph(escape(_fmt(c)), st["cell"]) for c in row["cells"]])

        table = Table(data, colWidths=[w for _, w in columns], repeatRows=1)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for index, row in enumerate(rows, start=1):
            band = BANDS.get(row.get("band") or "")
            if band:
                style.append(("BACKGROUND", (0, index), (-1, index), band[0]))
                style.append(("TEXTCOLOR", (0, index), (-1, index), band[1]))
        table.setStyle(TableStyle(style))
        story.append(table)

    if legend:
        story.append(Spacer(1, 7))
        for key, label in legend:
            fill, text = BANDS.get(key, (HEAD_BG, MUTED))
            # hexval() gives 0xrrggbb; reportlab's markup wants #rrggbb.
            story.append(Paragraph(
                f'<font backColor="#{fill.hexval()[2:]}" color="#{text.hexval()[2:]}">'
                f'&nbsp;&nbsp;&nbsp;&nbsp;</font> {escape(label)}', st["meta"]))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------- the reports

VU_COLUMNS = [
    ("Registration", 70), ("Asset", 50), ("Type", 62), ("Status", 44),
    ("Situation", 52), ("Depot", 120), ("Last download", 66),
    ("Days since<br/>last download", 66), ("Band", 44),
]

CARD_COLUMNS = [
    ("Name", 110), ("Card number", 86), ("Status", 40), ("Type", 50),
    ("Situation", 48), ("Home depot", 98), ("Last activity", 60),
    ("Days since<br/>activity", 50), ("Last download", 60),
    ("Days since<br/>last download", 58), ("Band", 40),
]

PERFORMANCE_COLUMNS = [
    ("Depot", 96), ("Driver", 110), ("Situation", 44), ("Type", 44),
    ("Level", 34), ("Points", 34), ("Level<br/>down", 36), ("Total<br/>items", 36),
    ("Items<br/>outstanding", 48), ("Open", 32), ("Accepted", 42),
    ("Disputed", 42), ("Last<br/>debriefed", 56), ("Earliest<br/>outstanding", 56),
    ("Latest<br/>outstanding", 56),
]


def _days_cell(days: int | None) -> str:
    return "Never" if days is None else str(days)


def render_vu_submission(rows: list[dict], company: str | None = None,
                         generated: datetime | None = None) -> bytes:
    table = [{
        "band": r["band"],
        "cells": [r["registration"], r["asset"], r["type"], r["status"],
                  r["situation"], r["depot"], _d(r["last_download"]),
                  _days_cell(r["days_since_download"]), r["band"].title()],
    } for r in rows]
    return render_table(
        "VU Download Submission", VU_COLUMNS, table, company=company,
        filters="All active vehicles, worst first. Vehicle units must be downloaded "
                "at least every 90 days.",
        legend=[("green", "14 days or less since last download"),
                ("amber", "Between 15 and 56 days since last download"),
                ("red", "57 days or more since last download, or never downloaded")],
        generated=generated,
        empty_note="No vehicles in this account.")


def render_card_submission(rows: list[dict], company: str | None = None,
                           generated: datetime | None = None) -> bytes:
    table = [{
        "band": r["band"],
        "cells": [r["name"], r["card_number"], r["status"], r["type"],
                  r["situation"], r["home_depot"], _d(r["last_activity"]),
                  _days_cell(r["days_since_activity"]), _d(r["last_download"]),
                  _days_cell(r["days_since_download"]), r["band"].title()],
    } for r in rows]
    return render_table(
        "Driver Card Submission", CARD_COLUMNS, table, company=company,
        filters="All active drivers, worst first. Driver cards must be downloaded "
                "at least every 28 days.",
        legend=[("green", "14 days or less since last download"),
                ("amber", "Between 15 and 28 days since last download"),
                ("red", "29 days or more since last download, or never downloaded")],
        generated=generated,
        empty_note="No drivers in this account.")


def render_performance(rows: list[dict], company: str | None = None,
                       generated: datetime | None = None) -> bytes:
    table = [{
        # Level is the finding here, so it carries the colour: 4 and 5 are the
        # drivers a transport manager has to be able to show they acted on.
        "band": "red" if r["level"] >= 4 else ("amber" if r["level"] == 3 else None),
        "cells": [r["depot"], r["driver_ref"], r["situation"], r["driver_type"],
                  f"Level {r['level']}", r["points"],
                  "Yes" if r["level_down_applied"] else "No",
                  r["total_items"], r["items_outstanding"], r["items_open"],
                  r["items_accepted"], r["items_disputed"],
                  _d(r["last_debriefed_on"]), _d(r["earliest_outstanding"]),
                  _d(r["latest_outstanding"])],
    } for r in rows]
    return render_table(
        "Outstanding Performance Item Summary", PERFORMANCE_COLUMNS, table,
        company=company,
        filters="Drivers with outstanding items, highest level first. An item is "
                "outstanding until it has been debriefed and signed.",
        legend=[("amber", "Level 3"), ("red", "Level 4 and above")],
        generated=generated,
        empty_note="No outstanding performance items.")


def render_wtd_grid(grid: dict, company: str | None = None,
                    generated: datetime | None = None) -> bytes:
    """Drivers down, weeks across. Built here rather than through render_table
    because the column count follows the reference period."""
    st = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=12 * mm,
        title="WTD Reference Period Summary", author=company or "")

    stamp = (generated or datetime.now(LOCAL_TZ)).strftime("%d/%m/%Y %H:%M")
    weeks = grid["week_starts"]
    story: list = []
    if company:
        story.append(Paragraph(escape(company), st["title"]))
    story.append(Paragraph("WTD Reference Period Summary", st["title"]))
    story.append(Paragraph(
        f"Generated {stamp}. {grid['reference_weeks']}-week reference period, "
        f"{_d(grid['period_start'])} to {_d(grid['period_end'])}. Hours shown are "
        "working time (driving and other work); periods of availability are excluded.",
        st["meta"]))
    story.append(Spacer(1, 6))

    drivers = grid.get("drivers") or []
    if not drivers:
        story.append(Paragraph("No working time recorded in this period.", st["empty"]))
        doc.build(story)
        return buffer.getvalue()

    header = [Paragraph("Driver", st["head"])]
    for index, ws in enumerate(weeks, start=1):
        header.append(Paragraph(f"Wk{index}<br/>{_d(ws)[:5]}", st["head"]))
    header += [Paragraph(x, st["head"]) for x in ("Weeks<br/>worked", "Average", "Max")]

    data = [header]
    flags: list[tuple[int, int]] = []
    for r_index, d in enumerate(drivers, start=1):
        cells = [Paragraph(escape(d["driver_ref"]), st["cell"])]
        for c_index, minutes in enumerate(d["cells"], start=1):
            # A week with no work is a dash, never 0.00: it is left out of the
            # average entirely, and printing zero would say it pulled it down.
            # A plain hyphen, not an en dash: the base-14 fonts encode it
            # everywhere, and this page gets photocopied and faxed.
            text = "-" if not minutes else f"{minutes / 60:.2f}"
            cells.append(Paragraph(text, st["cell"]))
            if minutes and minutes > grid["limits"]["week_minutes"]:
                flags.append((c_index, r_index))
        avg = d["average_minutes"]
        mx = d["max_minutes"]
        cells.append(Paragraph(str(d["weeks_worked"]), st["cell"]))
        cells.append(Paragraph("-" if avg is None else f"{avg / 60:.2f}", st["cell"]))
        cells.append(Paragraph("-" if mx is None else f"{mx / 60:.2f}", st["cell"]))
        data.append(cells)

    first = 74
    last = 38
    span = (doc.width - first - last * 3) / max(1, len(weeks))
    table = Table(data, colWidths=[first] + [span] * len(weeks) + [last] * 3,
                  repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    for col, row in flags:
        style.append(("BACKGROUND", (col, row), (col, row), BANDS["red"][0]))
        style.append(("TEXTCOLOR", (col, row), (col, row), BANDS["red"][1]))
    for r_index, d in enumerate(drivers, start=1):
        if d["over_average"]:
            avg_col = len(weeks) + 2
            style.append(("BACKGROUND", (avg_col, r_index), (avg_col, r_index), BANDS["red"][0]))
            style.append(("TEXTCOLOR", (avg_col, r_index), (avg_col, r_index), BANDS["red"][1]))
    table.setStyle(TableStyle(style))
    story.append(table)

    story.append(Spacer(1, 7))
    story.append(Paragraph(
        "A dash is a week with no working time on the card. Those weeks are left out "
        "of the average rather than counted as zero hours, so leave and sickness do "
        "not flatter the figure. Shaded cells are weeks over 60 hours; a shaded "
        "average is over the 48-hour limit for the reference period.", st["meta"]))

    doc.build(story)
    return buffer.getvalue()
