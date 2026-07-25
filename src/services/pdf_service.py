"""Quote PDF (deterministic ReportLab template), branded per hotel."""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.config.settings import QUOTES_DIR
from src.services import hotel_data_service
from src.services.pricing_service import format_mxn

ACCENT = colors.HexColor("#14532D")
LIGHT = colors.HexColor("#F0F5F1")


def generate_quote_pdf(ctx: dict) -> str:
    """ctx: hotel_code, reference (lead o reserva), guest_name, guest_contact,
    room_name, habitaciones, personas, check_in, check_out, quote (dict),
    payment_link, optional empresa/tipo_evento for groups."""
    hotel = hotel_data_service.get_hotel_info(ctx["hotel_code"])
    quote = ctx["quote"]
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = QUOTES_DIR / f"cotizacion_{ctx['reference']}.pdf"

    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], textColor=ACCENT, fontSize=20)
    subtitle = ParagraphStyle("Sub", parent=styles["Normal"], textColor=colors.grey, fontSize=9)
    heading = ParagraphStyle("H", parent=styles["Heading2"], textColor=ACCENT)

    doc = SimpleDocTemplate(str(path), pagesize=letter,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    story = [
        Paragraph(hotel["name"], title),
        Paragraph(f"{hotel['destino']} · {hotel['address']} · {hotel['phone']} · {hotel['email']}", subtitle),
        Paragraph("Un hotel del grupo TASMAN", subtitle),
        Spacer(1, 18),
        Paragraph(f"Cotización — {ctx['reference']}", heading),
        Spacer(1, 8),
    ]

    detail_rows = [
        ["Cliente", ctx["guest_name"]],
        ["Contacto", ctx["guest_contact"]],
    ]
    if ctx.get("empresa"):
        detail_rows.append(["Empresa", ctx["empresa"]])
    if ctx.get("tipo_evento"):
        detail_rows.append(["Tipo de evento", ctx["tipo_evento"]])
    detail_rows += [
        ["Habitación", f"{ctx['room_name']} × {ctx['habitaciones']}"],
        ["Personas", str(ctx["personas"])],
        ["Check-in", f"{ctx['check_in']} (desde las {hotel['check_in_time']})"],
        ["Check-out", f"{ctx['check_out']} (hasta las {hotel['check_out_time']})"],
    ]
    guest_table = Table(detail_rows, colWidths=[5 * cm, 11 * cm])
    guest_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [guest_table, Spacer(1, 16), Paragraph("Detalle de la tarifa", heading), Spacer(1, 8)]

    rows = [["Concepto", "Valor"]]
    rows.append([f"Alojamiento ({quote['nights']} noche(s) × {ctx['habitaciones']} hab. "
                 f"a {format_mxn(quote['nightly_rate'])}/noche)",
                 format_mxn(quote["room_subtotal"])])
    if quote.get("discount_pct"):
        rows.append([f"Descuento grupo ({quote['discount_pct']:.0f}% según ocupación)",
                     f"- {format_mxn(quote['discount_amount'])}"])
    rows.append(["IVA (16%)", format_mxn(quote["taxes"])])
    rows.append(["TOTAL", format_mxn(quote["total"])])

    price_table = Table(rows, colWidths=[11 * cm, 5 * cm])
    price_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
        ("TEXTCOLOR", (0, -1), (-1, -1), ACCENT),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [price_table, Spacer(1, 12)]

    if ctx.get("payment_link"):
        story += [Paragraph(f"<b>Garantiza tu reserva aquí:</b> {ctx['payment_link']}",
                            styles["Normal"]), Spacer(1, 12)]

    policies = " · ".join(f"<b>{p['policy']}:</b> {p['detail']}"
                          for p in hotel_data_service.get_policies(ctx["hotel_code"])[:3])
    story.append(Paragraph(policies, subtitle))

    doc.build(story)
    return str(path)
