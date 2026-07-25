"""Follow-up cadence from the sales flow: leads with no answer get a
reminder every 1 day (check-in < 7 days away), 3 days (7-14) or
5 days (14+). Deterministic templates — zero tokens."""

from datetime import date, timedelta

import pandas as pd

from src.services import leads_service, slack_service
from src.services.pricing_service import format_mxn


def cadence_days(check_in: date, today: date | None = None) -> int:
    today = today or date.today()
    days_to_arrival = (check_in - today).days
    if days_to_arrival < 7:
        return 1
    if days_to_arrival <= 14:
        return 3
    return 5


def next_followup_date(check_in: date, today: date | None = None) -> str:
    today = today or date.today()
    return (today + timedelta(days=cadence_days(check_in, today))).isoformat()


def followup_message(lead: dict) -> str:
    return (
        f"¡Hola {str(lead['guest_name']).split()[0]}! 👋 Te escribimos de "
        f"{lead['hotel']}: tu cotización por {format_mxn(lead['total_mxn'])} "
        f"({lead['check_in']} → {lead['check_out']}) sigue vigente y aún tenemos "
        f"disponibilidad. ¿Te ayudamos a confirmar tu reserva? "
        f"Puedes pagar aquí: https://pay.tasman.mx/{lead['lead_id']}"
    )


def run_pending(today: date | None = None) -> list[dict]:
    """Sends every due follow-up (console/Slack sim), reschedules the next
    one and returns what was sent. This is what the scheduler will call."""
    today = today or date.today()
    sent = []
    for lead in leads_service.due_followups(today):
        message = followup_message(lead)
        print(f"\n📨 [Seguimiento → {lead['guest_contact']}] {message}\n")
        check_in = pd.to_datetime(lead["check_in"]).date()
        followups = int(lead.get("followups_sent") or 0) + 1
        leads_service.update_individual_lead(
            lead["lead_id"],
            status=leads_service.STATUS_SEGUIMIENTO,
            followups_sent=followups,
            next_followup=next_followup_date(check_in, today),
        )
        if followups >= 3:
            slack_service.send(
                slack_service.CH_VENTAS_HQ,
                f"⏰ Lead {lead['lead_id']} ({lead['hotel']}) lleva {followups} "
                f"seguimientos sin respuesta. Sugerido: contacto humano.")
        sent.append({"lead_id": lead["lead_id"], "message": message})
    return sent
