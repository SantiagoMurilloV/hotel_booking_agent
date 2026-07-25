"""Group pipeline (flujo B): brief -> OCC -> discount -> quote draft ->
HUMAN VALIDATION (LangGraph interrupt, answered in console by the Tasman
advisor) -> send + register + Slack #grupos. And the group Closed Won node.

IMPORTANT: on resume after an interrupt the node re-runs from the top, so
every side effect (Excel writes, Slack) happens strictly AFTER interrupt().
"""

import json

import pandas as pd
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import interrupt
from pydantic import ValidationError

from src.config.settings import (DIRECTION_ROOMS, GROUP_MIN_PEOPLE,
                                 GROUP_MIN_ROOMS, HOTELS)
from src.models.schemas import GroupBrief
from src.services import (cloudbeds_service, crm_service, hotel_data_service,
                          leads_service, pdf_service, slack_service)
from src.services.pricing_service import build_quote, discount_for_occ, format_mxn


def _skip(tool_call) -> ToolMessage:
    return ToolMessage(content="Skipped: resolve after the group pipeline finishes.",
                       tool_call_id=tool_call["id"])


def group_pipeline_node(state: dict) -> dict:
    last = state["messages"][-1]
    briefs = [tc for tc in last.tool_calls if tc["name"] == "submit_group_brief"]
    others = [tc for tc in last.tool_calls if tc["name"] != "submit_group_brief"]
    tool_messages = [_skip(tc) for tc in others + briefs[1:]]
    tool_call = briefs[0]

    # ---- pure computation (safe to re-run on resume) ----
    try:
        brief = GroupBrief(**tool_call["args"])
    except ValidationError as exc:
        tool_messages.append(ToolMessage(
            content=f"Invalid group brief: {exc}. Ask for the missing fields.",
            tool_call_id=tool_call["id"]))
        return {"messages": tool_messages}

    if brief.habitaciones < GROUP_MIN_ROOMS and brief.personas < GROUP_MIN_PEOPLE:
        tool_messages.append(ToolMessage(
            content="This is not a group (needs 5+ rooms or 15+ people). "
                    "Use the individual flow with send_individual_proposal.",
            tool_call_id=tool_call["id"]))
        return {"messages": tool_messages}

    room_type_id = (tool_call["args"].get("room_type_id") or "").strip().upper()
    rooms_catalog = hotel_data_service.get_rooms(brief.hotel_code)
    room = (hotel_data_service.get_room(brief.hotel_code, room_type_id)
            if room_type_id else rooms_catalog[0])
    if room is None:
        room = rooms_catalog[0]

    units = cloudbeds_service.available_units(
        brief.hotel_code, room["room_type_id"], brief.check_in, brief.check_out)
    if units < brief.habitaciones:
        tool_messages.append(ToolMessage(
            content=f"Only {units} unit(s) of {room['name']} available for those "
                    "dates. Offer alternative dates/room type, or escalate to an "
                    "advisor to build a mixed-room block.",
            tool_call_id=tool_call["id"]))
        return {"messages": tool_messages}

    occ = cloudbeds_service.get_occupancy(brief.hotel_code, brief.check_in, brief.check_out)
    discount = discount_for_occ(occ)
    quote = build_quote(brief.hotel_code, room["room_type_id"],
                        brief.check_in, brief.check_out,
                        brief.habitaciones, discount_pct=discount)

    # ---- human validation (Tasman advisor) ----
    decision = interrupt({
        "type": "group_quote_validation",
        "hotel": HOTELS[brief.hotel_code],
        "contacto": brief.contacto,
        "empresa": brief.empresa or "—",
        "tipo_evento": brief.tipo_evento,
        "habitaciones": brief.habitaciones,
        "personas": brief.personas,
        "fechas": f"{brief.check_in} → {brief.check_out}",
        "room_type": f"{room['name']} ({room['room_type_id']})",
        "occ_pct": occ,
        "descuento_pct": discount,
        "nota_direccion": ("⚠️ 15+ habitaciones: se notificará a Dirección de Ventas"
                           if brief.habitaciones >= DIRECTION_ROOMS else ""),
        "cotizacion": {
            "noches": quote.nights,
            "tarifa_noche": format_mxn(quote.nightly_rate),
            "subtotal": format_mxn(quote.room_subtotal),
            "descuento": f"-{format_mxn(quote.discount_amount)} ({discount}%)",
            "iva_16": format_mxn(quote.taxes),
            "total": format_mxn(quote.total),
        },
    })

    # ---- side effects (run exactly once, after the advisor answered) ----
    action = str(decision.get("decision", "aprobar")).lower()
    asesor = str(decision.get("asesor", "Asesor Tasman"))
    nota = str(decision.get("nota", ""))

    if action == "rechazar":
        lead_id = leads_service.register_group_lead(
            brief.hotel_code, contacto=brief.contacto, empresa=brief.empresa,
            correo=brief.correo, tipo_evento=brief.tipo_evento,
            habitaciones=brief.habitaciones, personas=brief.personas,
            check_in=brief.check_in.isoformat(), check_out=brief.check_out.isoformat(),
            servicios=brief.servicios, occ_pct=occ, descuento_pct=0.0,
            total_mxn=0.0, status=leads_service.STATUS_BRIEF,
            notas=f"Cotización NO aprobada por {asesor}: {nota}")
        tool_messages.append(ToolMessage(
            content=json.dumps({
                "lead_id": lead_id,
                "status": "El asesor no aprobó el envío automático. Informa al "
                          "cliente que un asesor Tasman lo contactará hoy mismo "
                          "con su propuesta personalizada.",
            }, ensure_ascii=False),
            tool_call_id=tool_call["id"]))
        return {"messages": tool_messages}

    final_discount = discount
    if action in ("ajustar", "dto") and decision.get("descuento") is not None:
        final_discount = float(decision["descuento"])
        quote = build_quote(brief.hotel_code, room["room_type_id"],
                            brief.check_in, brief.check_out,
                            brief.habitaciones, discount_pct=final_discount)

    lead_id = leads_service.register_group_lead(
        brief.hotel_code, contacto=brief.contacto, empresa=brief.empresa,
        correo=brief.correo, tipo_evento=brief.tipo_evento,
        habitaciones=brief.habitaciones, personas=brief.personas,
        check_in=brief.check_in.isoformat(), check_out=brief.check_out.isoformat(),
        servicios=brief.servicios, occ_pct=occ, descuento_pct=final_discount,
        total_mxn=quote.total, status=leads_service.STATUS_PROPUESTA,
        aprobado_por=asesor,
        notas=f"room_type={room['room_type_id']}" + (f" · {nota}" if nota else ""))
    if brief.empresa:
        crm_service.upsert_b2b(brief.empresa, brief.contacto, brief.correo, brief.hotel_code)
    else:
        crm_service.upsert_b2c(brief.contacto, brief.correo, brief.hotel_code,
                               motivo=brief.tipo_evento)

    pdf_path = pdf_service.generate_quote_pdf({
        "hotel_code": brief.hotel_code, "reference": lead_id,
        "guest_name": brief.contacto, "guest_contact": brief.correo,
        "empresa": brief.empresa, "tipo_evento": brief.tipo_evento,
        "room_name": room["name"], "habitaciones": brief.habitaciones,
        "personas": brief.personas, "check_in": brief.check_in.isoformat(),
        "check_out": brief.check_out.isoformat(), "quote": quote.model_dump(),
        "payment_link": "",
    })

    lead = leads_service.get_group_lead(lead_id)
    slack_service.notify_group_lead(lead)
    if brief.habitaciones >= DIRECTION_ROOMS:
        slack_service.notify_direction(lead)

    tool_messages.append(ToolMessage(
        content=json.dumps({
            "lead_id": lead_id,
            "status": f"Cotización aprobada por {asesor} y lista para presentar al cliente.",
            "room": f"{room['name']} × {brief.habitaciones}",
            "noches": quote.nights,
            "occ_hotel": f"{occ}%",
            "descuento_grupo": f"{final_discount:.0f}%",
            "subtotal": format_mxn(quote.room_subtotal),
            "descuento_aplicado": f"-{format_mxn(quote.discount_amount)}",
            "iva_16": format_mxn(quote.taxes),
            "total": format_mxn(quote.total),
            "pdf": pdf_path,
            "condiciones": "Anticipo del 50% para bloquear; saldo 15 días antes. "
                           "Un asesor Tasman da seguimiento hoy mismo.",
        }, ensure_ascii=False),
        tool_call_id=tool_call["id"]))
    return {"messages": tool_messages}


def group_won_node(state: dict) -> dict:
    """Closed Won de grupo: bloque en Cloudbeds + Slack hotel/HQ + tarea rep."""
    last = state["messages"][-1]
    messages = []
    for tool_call in last.tool_calls:
        if tool_call["name"] != "create_group_reservation":
            messages.append(_skip(tool_call))
            continue
        lead_id = str(tool_call["args"].get("lead_id", "")).strip()
        lead = leads_service.get_group_lead(lead_id)
        if lead is None:
            messages.append(ToolMessage(
                content=f"Group lead {lead_id} not found (must start with GR-).",
                tool_call_id=tool_call["id"]))
            continue
        if lead["status"] == leads_service.STATUS_WON:
            messages.append(ToolMessage(
                content=f"Group {lead_id} is already CLOSED WON.",
                tool_call_id=tool_call["id"]))
            continue
        if int(lead["habitaciones"]) <= 0:
            messages.append(ToolMessage(
                content="This lead has no rooms (event only): the hotel team "
                        "closes it manually with the contract.",
                tool_call_id=tool_call["id"]))
            continue

        hotel_code = lead["hotel_code"]
        room_type = hotel_data_service.get_rooms(hotel_code)[0]["room_type_id"]
        for part in str(lead.get("notas") or "").split("·"):
            if "room_type=" in part:
                room_type = part.split("room_type=")[1].strip()
        check_in = pd.to_datetime(lead["check_in"]).date()
        check_out = pd.to_datetime(lead["check_out"]).date()
        cloudbeds_id = cloudbeds_service.create_reservation(
            hotel_code, room_type, int(lead["habitaciones"]),
            f"GRUPO {lead['empresa'] or lead['contacto']}",
            check_in, check_out, source="bot-grupo",
            notes=f"Lead {lead_id} · {lead['tipo_evento']} · contacto {lead['correo']}")
        leads_service.update_group_lead(lead_id,
                                        status=leads_service.STATUS_WON,
                                        cloudbeds_id=cloudbeds_id)
        lead = leads_service.get_group_lead(lead_id)
        slack_service.notify_group_won(lead, cloudbeds_id)

        messages.append(ToolMessage(
            content=f"Group block confirmed in Cloudbeds ({cloudbeds_id}).",
            tool_call_id=tool_call["id"]))
        messages.append(AIMessage(content=(
            f"🎉 ¡Excelente noticia! El grupo quedó confirmado.\n\n"
            f"• Bloqueo Cloudbeds: {cloudbeds_id}\n"
            f"• {lead['hotel']} · {lead['habitaciones']} habitaciones · "
            f"{lead['check_in']} → {lead['check_out']}\n"
            f"• Total: {format_mxn(lead['total_mxn'])}\n\n"
            f"El hotel y nuestro equipo de ventas ya fueron notificados. "
            f"Un asesor te enviará el contrato y el link del anticipo (50%) "
            f"en las próximas 48 horas. Después coordinamos los requerimientos "
            f"del grupo (72 h antes de la llegada). ¿Algo más por ahora?")))
    return {"messages": messages}
