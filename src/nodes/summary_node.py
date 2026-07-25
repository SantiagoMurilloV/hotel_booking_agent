"""Deterministic confirmation message after the individual post-booking
fan-out, opening the requirements + upsells conversation."""

from langchain_core.messages import AIMessage

from src.services.pricing_service import format_mxn


def summary_node(state: dict) -> dict:
    reservation = state["reservation"]

    notify = state.get("notify_result", "") or ""
    records = state.get("records_result", "") or ""
    warn_lines = []
    if "failed" in notify:
        warn_lines.append("⚠️ No pudimos avisar al hotel por Slack; lo haremos manualmente.")
    if "failed" in records:
        warn_lines.append(f"⚠️ Hubo un problema actualizando los registros ({records}).")
    warnings = ("\n".join(warn_lines) + "\n\n") if warn_lines else ""

    content = (
        f"✅ ¡Listo, {reservation['guest_name'].split()[0]}! Tu reserva quedó confirmada.\n\n"
        f"• Confirmación Cloudbeds: {reservation['cloudbeds_id']}\n"
        f"• {reservation['room_name']} × {reservation['habitaciones']} · "
        f"{reservation['check_in']} → {reservation['check_out']} "
        f"({reservation['personas']} persona(s))\n"
        f"• Total: {format_mxn(reservation['total'])}\n\n"
        f"Recibirás la confirmación de Cloudbeds por correo. "
        f"El equipo del hotel ya fue notificado. 📣\n\n"
        f"{warnings}"
        f"Para dejar todo listo: ¿tienes algún requerimiento especial? "
        f"(cuna, personas extra, llegada temprana o salida tarde, alergias). "
        f"Y si quieres, te comparto los tours y experiencias del hotel. 🌴"
    )
    return {
        "messages": [AIMessage(content=content)],
        "reservation": None,
        "notify_result": None,
        "records_result": None,
    }
