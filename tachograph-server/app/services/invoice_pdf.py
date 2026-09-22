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
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app.config import settings

logger = logging.getLogger("tacho.invoices")

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


def _issuer_block() -> list:
    """Who is issuing the invoice. A VAT number is required on the face of it."""
    lines = [settings.company_name, settings.company_address]
    parts = [Paragraph(f"<b>{lines[0]}</b>", SMALL)]
    for piece in [p.strip() for p in lines[1].split(",") if p.strip()]:
        parts.append(Paragraph(piece, SMALL))
    if settings.company_vat_number:
        parts.append(Spacer(1, 3))
        parts.append(Paragraph(f"VAT no. {settings.company_vat_number}", SMALL))
    if settings.company_number:
        parts.append(Paragraph(f"Company no. {settings.company_number}", SMALL))
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
               Paragraph(f"<b>{invoice.number}</b>", BODY),
               Paragraph(f"Issued {invoice.issued_on.strftime('%d %B %Y')}", SMALL)]
    masthead = Table([[logo or Paragraph(f"<b>{settings.company_name}</b>", H1), heading]],
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
                 Paragraph(f"<b>{customer_name}</b>", BODY)]
    if customer_email:
        billed_to.append(Paragraph(customer_email, SMALL))
    parties = Table([[
        [Paragraph("FROM", LABEL), Spacer(1, 3), *_issuer_block()],
        billed_to,
        [Paragraph("PERIOD", LABEL), Spacer(1, 3), Paragraph(invoice_period(invoice), BODY)],
    ]], colWidths=[62 * mm, 62 * mm, 50 * mm])
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
    ]))
    story += [parties, Spacer(1, 16)]

    # The charges.
    rows = [[Paragraph("<b>Description</b>", SMALL),
             Paragraph("<b>Rate</b>", ParagraphStyle("h", parent=SMALL, alignment=2)),
             Paragraph("<b>Amount</b>", ParagraphStyle("h", parent=SMALL, alignment=2))]]
    for line in lines:
        rows.append([Paragraph(line.description, BODY),
                     Paragraph(f"{money(line.rate)}/mo", RIGHT),
                     Paragraph(money(line.amount), RIGHT)])
    if len(rows) == 1:
        rows.append([Paragraph("No chargeable vehicles this period", SMALL),
                     Paragraph("", RIGHT), Paragraph(money(Decimal("0.00")), RIGHT)])

    charges = Table(rows, colWidths=[110 * mm, 32 * mm, 32 * mm], repeatRows=1)
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
        story.append(Paragraph(settings.invoice_payment_terms, SMALL))
    story += [Spacer(1, 6),
              Paragraph(f"Invoice {invoice.number} · {settings.company_name}", SMALL)]

    document.build(story)
    return buffer.getvalue()


def invoice_period(invoice) -> str:
    """The period in words, saying plainly when it is not a whole month."""
    if invoice.period_start.day == 1 and invoice.period_end.month == invoice.period_start.month:
        return invoice.period_start.strftime("%B %Y")
    start = f"{invoice.period_start.day} {invoice.period_start.strftime('%B')}"
    return f"{start} to {invoice.period_end.day} {invoice.period_end.strftime('%B %Y')}"
