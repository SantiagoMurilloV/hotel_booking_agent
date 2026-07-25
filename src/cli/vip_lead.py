"""Flujo C — VIPs: lead directo de Owner o Dirección, capturado por un
humano. Esta CLI asiste al asesor: captura el brief, consulta OCC en
Cloudbeds, aplica la tabla de descuentos, genera cotización + PDF y
registra todo en LEADS GRUPOS TASMAN y CRM (con las notificaciones Slack).

Run:  python -m src.cli.vip_lead
"""

from datetime import date

from src.config.settings import HOTELS
from src.services import (cloudbeds_service, crm_service, hotel_data_service,
                          leads_service, pdf_service, slack_service)
from src.services.pricing_service import build_quote, discount_for_occ, format_mxn


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"  {label}{suffix}: ").strip()
    return value or default


def main() -> None:
    print("=" * 60)
    print("  TASMAN — Captura de lead VIP (flujo C · asesor)")
    print("=" * 60)
    print("  Hoteles: " + " · ".join(f"{c}={n}" for c, n in HOTELS.items()))

    hotel_code = _ask("Hotel (código)").upper()
    if hotel_code not in HOTELS:
        print("  Código de hotel inválido."); return
    asesor = _ask("Tu nombre (asesor)")
    contacto = _ask("Nombre del contacto")
    empresa = _ask("Empresa / agencia (vacío si privado)")
    correo = _ask("Correo o teléfono")
    tipo_evento = _ask("Tipo de evento (corporativo, boda, retiro...)")
    habitaciones = int(_ask("Habitaciones"))
    personas = int(_ask("Personas"))
    check_in = date.fromisoformat(_ask("Check-in (YYYY-MM-DD)"))
    check_out = date.fromisoformat(_ask("Check-out (YYYY-MM-DD)"))
    servicios = _ask("Servicios requeridos")

    rooms = hotel_data_service.get_rooms(hotel_code)
    print("  Tipos de habitación: " + " · ".join(
        f"{r['room_type_id']}={r['name']} ({format_mxn(r['base_rate_mxn'])})" for r in rooms))
    room_type = _ask("Tipo de habitación base", rooms[0]["room_type_id"]).upper()

    occ = cloudbeds_service.get_occupancy(hotel_code, check_in, check_out)
    discount = discount_for_occ(occ)
    print(f"\n  OCC Cloudbeds: {occ}% → descuento por tabla: {discount}%")
    override = _ask("Descuento a aplicar (%)", str(discount))
    discount = float(override)

    quote = build_quote(hotel_code, room_type, check_in, check_out,
                        habitaciones, discount_pct=discount)
    print(f"\n  Cotización: {quote.nights} noche(s) × {habitaciones} hab · "
          f"subtotal {format_mxn(quote.room_subtotal)} · "
          f"dto -{format_mxn(quote.discount_amount)} · IVA {format_mxn(quote.taxes)}"
          f" · TOTAL {format_mxn(quote.total)}")
    if input("  ¿Registrar y enviar? (s/n): ").strip().lower() not in ("s", "si", "sí"):
        print("  Cancelado; no se registró nada."); return

    lead_id = leads_service.register_group_lead(
        hotel_code, contacto=contacto, empresa=empresa, correo=correo,
        tipo_evento=f"{tipo_evento} (VIP)", habitaciones=habitaciones,
        personas=personas, check_in=check_in.isoformat(),
        check_out=check_out.isoformat(), servicios=servicios, occ_pct=occ,
        descuento_pct=discount, total_mxn=quote.total,
        status=leads_service.STATUS_PROPUESTA, aprobado_por=asesor,
        canal="VIP/llamada", notas=f"room_type={room_type}")
    if empresa:
        crm_service.upsert_b2b(empresa, contacto, correo, hotel_code, origen="VIP")
    else:
        crm_service.upsert_b2c(contacto, correo, hotel_code,
                               motivo=tipo_evento, origen="VIP")
    room = hotel_data_service.get_room(hotel_code, room_type)
    pdf_path = pdf_service.generate_quote_pdf({
        "hotel_code": hotel_code, "reference": lead_id, "guest_name": contacto,
        "guest_contact": correo, "empresa": empresa, "tipo_evento": tipo_evento,
        "room_name": room["name"], "habitaciones": habitaciones,
        "personas": personas, "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(), "quote": quote.model_dump(),
        "payment_link": "",
    })
    lead = leads_service.get_group_lead(lead_id)
    slack_service.notify_group_lead(lead)
    if habitaciones >= 15:
        slack_service.notify_direction(lead)

    print(f"\n  ✅ Lead {lead_id} registrado en LEADS GRUPOS TASMAN.")
    print(f"  📄 Cotización PDF: {pdf_path}")
    print("  📣 Slack #grupos notificado. Envía la propuesta al cliente de inmediato.")


if __name__ == "__main__":
    main()
