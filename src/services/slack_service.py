"""Slack notifications for every audience in the sales flow:
#grupos (HQ), #ventas-hq, #direccion-ventas and one ops channel per hotel.
Without SLACK_WEBHOOK_URL everything prints to console (simulation mode),
which is the agreed behaviour for the console-only phase."""

import json

import requests

from src.config.settings import HOTELS, SLACK_WEBHOOK_URL
from src.services.pricing_service import format_mxn

CH_GRUPOS = "#grupos"
CH_VENTAS_HQ = "#ventas-hq"
CH_DIRECCION = "#direccion-ventas"


def hotel_channel(hotel_code: str) -> str:
    return f"#operativo-{HOTELS[hotel_code].lower().replace(' ', '-')}"


def _print_simulation(channel: str, text: str, blocks: list[dict] | None) -> None:
    print(f"\n--- [Slack → {channel}] ---")
    if blocks:
        print(json.dumps(blocks, indent=2, ensure_ascii=False))
    else:
        print(text)
    print("--- fin del mensaje ---\n")


def send(channel: str, text: str, blocks: list[dict] | None = None) -> str:
    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if not SLACK_WEBHOOK_URL:
        _print_simulation(channel, text, blocks)
        return "simulated (no webhook configured)"
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        return "sent to Slack"
    except requests.RequestException as exc:
        # Never let a notification kill the sales flow: fall back to console.
        _print_simulation(channel, text, blocks)
        return f"webhook failed ({type(exc).__name__}), printed to console"


def _fields(pairs: list[tuple[str, str]]) -> dict:
    return {"type": "section", "fields": [
        {"type": "mrkdwn", "text": f"*{label}:*\n{value}"} for label, value in pairs]}


def notify_group_lead(lead: dict, creative_message: str = "") -> str:
    """#grupos: brief + cotización enviada, para que HQ dé seguimiento (SLA 2 h)."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
         "text": "📊 Nueva cotización de grupo enviada", "emoji": True}},
    ]
    if creative_message:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": creative_message}})
    blocks += [
        {"type": "divider"},
        _fields([("Lead", lead["lead_id"]), ("Hotel", lead["hotel"]),
                 ("Contacto", f"{lead['contacto']} · {lead['correo']}"),
                 ("Empresa", lead.get("empresa") or "—"),
                 ("Evento", lead["tipo_evento"]),
                 ("Hab. / personas", f"{lead['habitaciones']} / {lead['personas']}"),
                 ("Fechas", f"{lead['check_in']} → {lead['check_out']}"),
                 ("OCC / dto", f"{lead['occ_pct']}% / {lead['descuento_pct']}%"),
                 ("Total cotizado", format_mxn(lead["total_mxn"])),
                 ("Aprobó", lead.get("aprobado_por") or "—")]),
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": "SLA: asesor HQ toma el caso en máx. 2 h hábiles · da seguimiento y cierra"}]},
    ]
    return send(CH_GRUPOS, f"Cotización de grupo {lead['lead_id']} enviada", blocks)


def notify_direction(lead: dict) -> str:
    """+15 habitaciones: valida Dirección de Ventas."""
    text = (f"⚠️ Dirección de Ventas: grupo {lead['lead_id']} con "
            f"{lead['habitaciones']} habitaciones en {lead['hotel']} "
            f"({lead['check_in']} → {lead['check_out']}). Requiere su validación.")
    return send(CH_DIRECCION, text)


def notify_new_booking(reservation: dict, creative_message: str) -> str:
    """Hotel ops channel: nueva reserva individual confirmada."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
         "text": "🏨 ¡Nueva reserva confirmada!", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": creative_message}},
        {"type": "divider"},
        _fields([("Cloudbeds", reservation["cloudbeds_id"]),
                 ("Huésped", reservation["guest_name"]),
                 ("Habitación", f"{reservation['room_name']} × {reservation['habitaciones']}"),
                 ("Personas", str(reservation["personas"])),
                 ("Check-in", str(reservation["check_in"])),
                 ("Check-out", str(reservation["check_out"])),
                 ("Total", format_mxn(reservation["total"]))]),
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": f"Contacto: {reservation['guest_contact']} · Lead {reservation['lead_id']} · Generado por el bot de ventas"}]},
    ]
    return send(hotel_channel(reservation["hotel_code"]),
                f"Nueva reserva {reservation['cloudbeds_id']}", blocks)


def notify_group_won(lead: dict, cloudbeds_id: str) -> None:
    """Closed Won de grupo: Slack hotel + Slack HQ + tarea para el sales rep."""
    hotel_code = lead["hotel_code"]
    send(hotel_channel(hotel_code),
         f"✅ Grupo confirmado {lead['lead_id']} · Cloudbeds {cloudbeds_id} · "
         f"{lead['habitaciones']} hab · {lead['check_in']} → {lead['check_out']} · "
         f"{lead['tipo_evento']} · contacto {lead['contacto']}")
    send(CH_VENTAS_HQ,
         f"🏆 CLOSED WON grupo {lead['lead_id']} en {lead['hotel']} por "
         f"{format_mxn(lead['total_mxn'])} · Cloudbeds {cloudbeds_id}")
    send(CH_VENTAS_HQ,
         f"📋 Tarea para sales rep: contrato + anticipo 50% del grupo "
         f"{lead['lead_id']} (SLA 48 h) · requerimientos 72 h antes de llegada")


def notify_host_requirements(cloudbeds_id: str, hotel_code: str,
                             guest_name: str, check_in: str,
                             requirements: str) -> str:
    text = (f"📝 Requerimientos para {cloudbeds_id} ({guest_name}, "
            f"llegada {check_in}): {requirements} · Preparar 48 h antes de la llegada.")
    return send(hotel_channel(hotel_code), text)


def notify_upsell(cloudbeds_id: str, hotel_code: str, guest_name: str,
                  upsell: str) -> str:
    text = (f"🎯 Upsell solicitado en {cloudbeds_id} ({guest_name}): {upsell}. "
            f"Host: confirmar disponibilidad en máx. 4 h.")
    return send(hotel_channel(hotel_code), text)


def notify_escalation(hotel_code: str, motivo: str, resumen: str) -> str:
    text = (f"🚨 Escalación a asesor · {HOTELS[hotel_code]} · Motivo: {motivo}\n"
            f"{resumen}\nSLA: asesor toma el caso en máx. 2 h hábiles.")
    send(hotel_channel(hotel_code), text)
    return send(CH_VENTAS_HQ, text)


def notify_event_brief(lead: dict) -> str:
    """Evento sin habitaciones: supervisión del hotel cotiza (humano)."""
    text = (f"🎪 Nuevo evento sin habitaciones {lead['lead_id']} en {lead['hotel']}: "
            f"{lead['tipo_evento']} para {lead['personas']} personas el {lead['check_in']}. "
            f"Servicios: {lead['servicios']}. Contacto: {lead['contacto']} · {lead['correo']}. "
            f"Supervisión: generar cotización de centros de consumo.")
    send(hotel_channel(lead["hotel_code"]), text)
    return send(CH_VENTAS_HQ, text)


def send_report(channel: str, title: str, body: str) -> str:
    return send(channel, f"*{title}*\n{body}")
