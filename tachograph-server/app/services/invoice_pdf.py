"""The invoice as the customer receives it.

A VAT invoice has to carry particular things to be valid: who issued it, their
VAT number, an invoice number, the date, what was supplied, and the VAT shown
separately. Those are the parts that are not decoration, so they are not
optional here - the number and the VAT breakdown are always drawn.

The logo is drawn if the file is there and skipped quietly if it is not, so a
missing image never stops an invoice going out.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from xml.sax.saxutils import escape
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app.config import settings
from app.services import billing

logger = logging.getLogger("tacho.invoices")

PENNY = Decimal("0.01")

INK = colors.HexColor("#1a1f27")
MUTED = colors.HexColor("#5d6874")
RULE = colors.HexColor("#d8dde4")
BRAND = colors.HexColor("#e8620f")      # the orange from the D&H mark

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11.5, textColor=MUTED)
H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=INK)
LABEL = ParagraphStyle("label", parent=SMALL, fontName="Helvetica-Bold", textColor=MUTED)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=2)
RIGHT_BOLD = ParagraphStyle("rightbold", parent=RIGHT, fontName="Helvetica-Bold")


def money(amount: Decimal) -> str:
    return f"£{Decimal(amount):,.2f}"


# What a charge is called on the paper, rather than what it is called in code.
SERVICE_NAMES = dict(billing.PACKAGE_NAMES)


def group(lines) -> list[dict]:
    """Charges by service rather than by vehicle.

    A customer with forty vehicles does not want forty lines; they want to see
    what each service costs and how many they are paying for. So a line is one
    service at one rate, and the quantity is the number of vehicles on it.

    Two things are deliberately kept apart rather than merged. Vehicles charged
    for part of a month cannot join the whole-month line, because the amounts
    differ - and that separate line is the honest place to explain the odd
    figure. And on a quarterly invoice a vehicle billed for two months cannot
    join one billed for three, for the same reason.

    Everything in a bucket was therefore charged identically, which is what
    makes the line arithmetic check out: quantity times the unit price is the
    amount, exactly.
    """
    # First by vehicle, so a vehicle billed for several months of the same
    # period is counted once and its months counted rather than its lines.
    per_vehicle: dict[tuple, dict] = {}
    for line in lines:
        part_month = line.days < line.days_in_month
        shape = (line.item, Decimal(line.rate),
                 (line.days, line.days_in_month) if part_month else None)
        entry = per_vehicle.setdefault((*shape, line.vehicle), {
            "shape": shape, "months": 0, "amount": Decimal("0.00"),
            "days": line.days, "days_in_month": line.days_in_month,
            "part_month": part_month,
        })
        entry["months"] += 1
        entry["amount"] += Decimal(line.amount)

    buckets: dict[tuple, dict] = {}
    for entry in per_vehicle.values():
        key = (*entry["shape"], entry["months"])
        bucket = buckets.setdefault(key, {
            "item": entry["shape"][0], "rate": entry["shape"][1], "quantity": 0,
            "amount": Decimal("0.00"), "days": entry["days"],
            "days_in_month": entry["days_in_month"],
            "part_month": entry["part_month"], "months": entry["months"],
        })
        bucket["quantity"] += 1
        bucket["amount"] += entry["amount"]

    ordered = sorted(buckets.values(),
                     key=lambda b: (list(SERVICE_NAMES).index(b["item"])
                                    if b["item"] in SERVICE_NAMES else 99,
                                    b["part_month"], -float(b["rate"]), -b["months"]))
    for bucket in ordered:
        name = SERVICE_NAMES.get(bucket["item"], bucket["item"].title())
        # The unit price is what one vehicle cost for the whole period, so the
        # line reads as vehicles times price and adds up to the amount.
        bucket["unit"] = (bucket["amount"] / bucket["quantity"]).quantize(
            PENNY, rounding=ROUND_HALF_UP)
        if bucket["part_month"]:
            basis = (f"{bucket['days']} of {bucket['days_in_month']} days "
                     f"at {money(bucket['rate'])}/month")
            if bucket["months"] > 1:
                basis = f"{bucket['months']} × {basis}"
        elif bucket["months"] > 1:
            basis = f"{bucket['months']} months at {money(bucket['rate'])}/month"
        else:
            basis = f"{money(bucket['rate'])}/month"
        bucket["description"] = f"{name} — {basis}"
    return ordered


def _logo():
    """The company mark, at a sensible width, or nothing if it is not there."""
    path = Path(settings.invoice_logo_path)
    if not path.is_file():
        return None
    try:
        image = Image(str(path))
        ratio = image.imageHeight / image.imageWidth
        image.drawWidth = 42 * mm
        image.drawHeight = 42 * mm * ratio
        image.hAlign = "LEFT"
        return image
    except Exception:  # noqa: BLE001 - an unreadable logo must not stop an invoice
        logger.exception("the invoice logo could not be drawn")
        return None


def text(value) -> str:
    """One piece of text, safe to put in a drawn paragraph.

    ReportLab reads a paragraph as mini-HTML, so an ampersand in a name is
    taken for the start of an entity: "D&H Group Ltd" comes out as "D&H;
    Group Ltd" on the finished invoice. Company names contain ampersands all
    the time, so every value that comes from data goes through here, and only
    the tags this module writes itself are left as markup.
    """
    return escape(str(value if value is not None else ""))


def placeholder(value: str | None) -> bool:
    """Whether a registration number is a stand-in rather than a real one.

    A missing company number on an invoice is unremarkable. A made-up one is a
    false statement on a VAT document, so anything that is only zeros is
    treated as not set and simply left off.
    """
    digits = re.sub(r"[^0-9]", "", value or "")
    return not digits or set(digits) == {"0"}


def vat_display(value: str | None) -> str:
    """The VAT number as it should read on an invoice.

    A UK registration is shown with its country prefix and in its usual
    grouping - GB 407 4404 21 - which is what a customer's accounts department
    expects to see. Anything already carrying a prefix is left exactly as it
    was typed, so a non-UK or unusual number is never rewritten.
    """
    given = (value or "").strip()
    if re.search(r"[A-Za-z]", given):
        return given
    digits = re.sub(r"[^0-9]", "", given)
    if len(digits) == 9:
        return f"GB {digits[:3]} {digits[3:7]} {digits[7:]}"
    return given


def _issuer_block() -> list:
    """Who is issuing the invoice. A VAT number is required on the face of it."""
    parts = [Paragraph(f"<b>{text(settings.company_name)}</b>", SMALL)]
    for piece in [p.strip() for p in (settings.company_address or "").split(",") if p.strip()]:
        parts.append(Paragraph(text(piece), SMALL))
    if not placeholder(settings.company_vat_number):
        parts.append(Spacer(1, 3))
        parts.append(Paragraph(f"VAT no. {text(vat_display(settings.company_vat_number))}", SMALL))
    if not placeholder(settings.company_number):
        parts.append(Paragraph(f"Company no. {text(settings.company_number)}", SMALL))
    return parts


def render(invoice, lines, *, customer_name: str, customer_email: str | None = None) -> bytes:
    """Draw one invoice and hand back the PDF.

    `invoice` carries the totals and the period; `lines` are the charges. Both
    come from the stored record, never recalculated, so a reissued copy of an
    invoice is identical to the one the customer was sent.
    """
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, title=f"Invoice {invoice.number}",
        author=settings.company_name, subject=f"Invoice {invoice.number}",
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm)

    story: list = []

    # Masthead: the mark on the left, the invoice's own details on the right.
    logo = _logo()
    heading = [Paragraph("INVOICE", H1),
               Spacer(1, 4),
               Paragraph(f"<b>{text(invoice.number)}</b>", BODY),
               Paragraph(f"Issued {invoice.issued_on.strftime('%d %B %Y')}", SMALL)]
    masthead = Table([[logo or Paragraph(f"<b>{text(settings.company_name)}</b>", H1), heading]],
                     colWidths=[85 * mm, 89 * mm])
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [masthead, Spacer(1, 14)]

    # Who it is from, who it is to, and what it covers.
    billed_to = [Paragraph("BILLED TO", LABEL), Spacer(1, 3),
                 Paragraph(f"<b>{text(customer_name)}</b>", BODY)]
    if customer_email:
        billed_to.append(Paragraph(text(customer_email), SMALL))
    parties = Table([[
        [Paragraph("FROM", LABEL), Spacer(1, 3), *_issuer_block()],
        billed_to,
        [Paragraph("PERIOD", LABEL), Spacer(1, 3), Paragraph(text(invoice_period(invoice)), BODY)],
    ]], colWidths=[62 * mm, 62 * mm, 50 * mm])
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
    ]))
    story += [parties, Spacer(1, 16)]

    # The charges.
    heading = ParagraphStyle("h", parent=SMALL, alignment=2)
    rows = [[Paragraph("<b>Description</b>", SMALL),
             Paragraph("<b>Vehicles</b>", heading),
             Paragraph("<b>Each</b>", heading),
             Paragraph("<b>Amount</b>", heading)]]
    for charge in group(lines):
        rows.append([Paragraph(text(charge["description"]), BODY),
                     Paragraph(str(charge["quantity"]), RIGHT),
                     Paragraph(money(charge["unit"]), RIGHT),
                     Paragraph(money(charge["amount"]), RIGHT)])
    if len(rows) == 1:
        rows.append([Paragraph("No chargeable vehicles this period", SMALL),
                     Paragraph("", RIGHT), Paragraph("", RIGHT),
                     Paragraph(money(Decimal("0.00")), RIGHT)])

    charges = Table(rows, colWidths=[92 * mm, 22 * mm, 30 * mm, 30 * mm], repeatRows=1)
    charges.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
    ]))
    story += [charges, Spacer(1, 10)]

    # Totals, with VAT shown separately as a VAT invoice must.
    vat_percent = (Decimal(invoice.vat_rate) * 100).quantize(Decimal("1"))
    totals = Table([
        [Paragraph("Subtotal", RIGHT), Paragraph(money(invoice.net), RIGHT)],
        [Paragraph(f"VAT at {vat_percent}%", RIGHT), Paragraph(money(invoice.vat), RIGHT)],
        [Paragraph("<b>Total due</b>", RIGHT_BOLD), Paragraph(f"<b>{money(invoice.total)}</b>", RIGHT_BOLD)],
    ], colWidths=[142 * mm, 32 * mm])
    totals.setStyle(TableStyle([
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
    ]))
    story += [totals, Spacer(1, 18)]

    if settings.invoice_payment_terms:
        story.append(Paragraph(text(settings.invoice_payment_terms), SMALL))
    story += [Spacer(1, 6),
              Paragraph(f"Invoice {text(invoice.number)} · {text(settings.company_name)}", SMALL)]

    document.build(story)
    return buffer.getvalue()


def invoice_period(invoice) -> str:
    """The period in words, saying plainly when it is not a whole month."""
    if (invoice.period_start.day == 1
            and (invoice.period_start.year, invoice.period_start.month)
            == (invoice.period_end.year, invoice.period_end.month)):
        return invoice.period_start.strftime("%B %Y")
    start = f"{invoice.period_start.day} {invoice.period_start.strftime('%B')}"
    if invoice.period_start.year != invoice.period_end.year:
        start += f" {invoice.period_start.year}"
    return f"{start} to {invoice.period_end.day} {invoice.period_end.strftime('%B %Y')}"
