"""Parallel fan-out after an individual reservation is confirmed:
Slack notification (LLM creative message) + records update (LEADS/CRM)."""

from langchain_core.messages import HumanMessage

from src.config.settings import llm_factory
from src.services import crm_service, leads_service, slack_service
from src.services.pricing_service import format_mxn

CREATIVE_MESSAGE_PROMPT = """Write a short, fun, high-energy Slack announcement \
in Mexican Spanish (2-3 lines max, with emojis) telling the hotel operations \
team there is a new confirmed reservation. Make it feel like a small celebration, \
not a boring system notification. Do not repeat the structured data (name, dates, \
room) — that is shown separately below your message. Reservation context: guest \
{guest_name}, room {room_name}, starting {check_in}, total {total}.
Reply with the message text only."""

FALLBACK_MESSAGE = ("🎉 ¡Cayó una nueva reserva, equipo! A preparar esa "
                    "bienvenida de lujo que nos caracteriza. 🛎️✨")


def notify_node(state: dict) -> dict:
    reservation = state["reservation"]
    try:
        llm = llm_factory(temperature=0.9)
        prompt = CREATIVE_MESSAGE_PROMPT.format(
            guest_name=reservation["guest_name"],
            room_name=reservation["room_name"],
            check_in=reservation["check_in"],
            total=format_mxn(reservation["total"]))
        creative_message = llm.invoke([HumanMessage(content=prompt)]).content.strip()
    except Exception:
        creative_message = FALLBACK_MESSAGE
    try:
        status = slack_service.notify_new_booking(reservation, creative_message)
        return {"notify_result": f"Hotel notified ({status})."}
    except Exception as exc:
        return {"notify_result": f"Slack notification failed: {exc}"}


def records_node(state: dict) -> dict:
    reservation = state["reservation"]
    try:
        leads_service.update_individual_lead(
            reservation["lead_id"],
            status=leads_service.STATUS_WON,
            cloudbeds_id=reservation["cloudbeds_id"],
            next_followup="")
        crm_service.upsert_b2c(reservation["guest_name"],
                               reservation["guest_contact"],
                               reservation["hotel_code"],
                               motivo=reservation.get("motivo", ""))
        return {"records_result": "LEADS y CRM actualizados (Closed Won)."}
    except Exception as exc:
        return {"records_result": f"Records update failed: {exc}"}
