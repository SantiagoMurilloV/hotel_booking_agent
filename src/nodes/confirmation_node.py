"""Deterministic gate for individual reservations: validates the lead,
re-checks availability and creates the reservation in Cloudbeds."""

import pandas as pd
from langchain_core.messages import ToolMessage

from src.services import cloudbeds_service, hotel_data_service, leads_service


def confirmation_node(state: dict) -> dict:
    last = state["messages"][-1]
    tool_messages = []
    reservation = None

    for tool_call in last.tool_calls:
        if tool_call["name"] != "create_reservation":
            tool_messages.append(ToolMessage(
                content="Skipped: resolve after the reservation is processed.",
                tool_call_id=tool_call["id"]))
            continue

        lead_id = str(tool_call["args"].get("lead_id", "")).strip()
        lead = leads_service.get_individual_lead(lead_id)
        if lead is None:
            tool_messages.append(ToolMessage(
                content=f"Lead {lead_id} not found. Send the proposal first "
                        "with send_individual_proposal.",
                tool_call_id=tool_call["id"]))
            continue
        if lead["status"] in (leads_service.STATUS_WON, leads_service.STATUS_LOST):
            tool_messages.append(ToolMessage(
                content=f"Lead {lead_id} is already {lead['status']}.",
                tool_call_id=tool_call["id"]))
            continue

        hotel_code = lead["hotel_code"]
        check_in = pd.to_datetime(lead["check_in"]).date()
        check_out = pd.to_datetime(lead["check_out"]).date()
        habitaciones = int(lead["habitaciones"])
        units = cloudbeds_service.available_units(
            hotel_code, lead["room_type_id"], check_in, check_out)
        if units < habitaciones:
            tool_messages.append(ToolMessage(
                content=f"Availability changed: only {units} unit(s) left. "
                        "Offer alternative dates or another room and re-quote.",
                tool_call_id=tool_call["id"]))
            continue

        cloudbeds_id = cloudbeds_service.create_reservation(
            hotel_code, lead["room_type_id"], habitaciones,
            lead["guest_name"], check_in, check_out,
            notes=f"Lead {lead_id} · {lead['guest_contact']}")
        room = hotel_data_service.get_room(hotel_code, lead["room_type_id"])
        reservation = {
            "lead_id": lead_id,
            "hotel_code": hotel_code,
            "cloudbeds_id": cloudbeds_id,
            "guest_name": lead["guest_name"],
            "guest_contact": lead["guest_contact"],
            "room_name": room["name"] if room else lead["room_type_id"],
            "habitaciones": habitaciones,
            "personas": int(lead["personas"]),
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "total": float(lead["total_mxn"]),
            "motivo": str(lead.get("motivo") or ""),
        }
        tool_messages.append(ToolMessage(
            content=f"Reservation confirmed in Cloudbeds with id {cloudbeds_id}. "
                    "Post-booking pipeline triggered.",
            tool_call_id=tool_call["id"]))

    return {"messages": tool_messages, "reservation": reservation}
