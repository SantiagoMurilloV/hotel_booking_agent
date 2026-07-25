"""LLM-facing tools for the Tasman sales bot. Thin wrappers over services
returning compact JSON. `create_reservation`, `submit_group_brief` and
`create_group_reservation` are intercepted by the graph router — their
bodies never execute."""

import json
from datetime import date

from langchain_core.tools import tool
from pydantic import ValidationError

from src.config.settings import GROUP_MIN_PEOPLE, GROUP_MIN_ROOMS
from src.models.schemas import EventBrief, ProposalRequest
from src.services import (cloudbeds_service, crm_service, hotel_data_service,
                          leads_service, pdf_service, slack_service)
from src.services.followup_service import next_followup_date
from src.services.pricing_service import build_quote, format_mxn


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


@tool
def list_hotels() -> str:
    """Directory of the 6 Tasman hotels (code, name, destination, category,
    short description). Use it to recommend the right hotel of the group."""
    return json.dumps(hotel_data_service.hotel_directory(), ensure_ascii=False)


@tool
def get_hotel_info(hotel_code: str, topic: str) -> str:
    """Ficha técnica lookup for one hotel. hotel_code: AMINA, CALIZA, SAL,
    TALAVERA, LAIVA or SANTA. topic values: 'general' (address, times,
    description), 'habitaciones' (room types), 'politicas' (policies),
    'upsells' (tours, pick-up, experiences with prices), 'salones' (event
    spaces for groups)."""
    code = hotel_code.strip().upper()
    topic = topic.strip().lower()
    lookups = {
        "general": hotel_data_service.get_hotel_info,
        "habitaciones": hotel_data_service.get_rooms,
        "politicas": hotel_data_service.get_policies,
        "upsells": hotel_data_service.get_upsells,
        "salones": hotel_data_service.get_event_spaces,
    }
    if topic not in lookups:
        return "Invalid topic. Use: general, habitaciones, politicas, upsells, salones."
    try:
        return json.dumps(lookups[topic](code), ensure_ascii=False, default=str)
    except (KeyError, FileNotFoundError):
        return "Unknown hotel code. Valid: AMINA, CALIZA, SAL, TALAVERA, LAIVA, SANTA."


@tool
def check_availability(hotel_code: str, check_in: str, check_out: str) -> str:
    """Live availability and rate per room type from Cloudbeds for a hotel
    and date range. Dates in YYYY-MM-DD."""
    code = hotel_code.strip().upper()
    rooms = cloudbeds_service.availability_by_room(
        code, _parse_date(check_in), _parse_date(check_out))
    payload = [{**r, "rate_mxn": format_mxn(r["rate_mxn"])} for r in rooms]
    return json.dumps(payload, ensure_ascii=False)


@tool
def send_individual_proposal(hotel_code: str, guest_name: str, guest_contact: str,
                             motivo: str, personas: int, habitaciones: int,
                             room_type_id: str, check_in: str, check_out: str) -> str:
    """Send the formal proposal for an INDIVIDUAL booking (1-4 rooms):
    computes the exact quote, registers the lead in the hotel's LEADS file,
    generates the PDF and returns the quote plus payment link. Call it once
    you have: name, contact, dates, hotel, room type, people and motive."""
    if habitaciones >= GROUP_MIN_ROOMS or personas >= GROUP_MIN_PEOPLE:
        return (f"This is a GROUP ({habitaciones} rooms / {personas} people). "
                "Use submit_group_brief instead.")
    try:
        req = ProposalRequest(
            hotel_code=hotel_code, guest_name=guest_name,
            guest_contact=guest_contact, motivo=motivo,
            room_type_id=room_type_id, habitaciones=habitaciones,
            personas=personas, check_in=check_in, check_out=check_out)
    except ValidationError as exc:
        return f"Invalid proposal data: {exc}. Ask the guest for the missing fields."

    room = hotel_data_service.get_room(req.hotel_code, req.room_type_id)
    if room is None:
        return "Unknown room type for that hotel. Check with check_availability."
    if req.personas > int(room["capacity"]) * req.habitaciones:
        return (f"Capacity exceeded: {req.habitaciones} x {room['name']} holds "
                f"{int(room['capacity']) * req.habitaciones} guests max. "
                "Suggest more rooms or a bigger room type.")
    units = cloudbeds_service.available_units(
        req.hotel_code, req.room_type_id, req.check_in, req.check_out)
    if units < req.habitaciones:
        return (f"Only {units} unit(s) of {room['name']} available on those dates. "
                "Offer alternative dates, another room type or another Tasman hotel.")

    quote = build_quote(req.hotel_code, req.room_type_id,
                        req.check_in, req.check_out, req.habitaciones)
    lead_id = leads_service.register_individual_lead(
        req.hotel_code, guest_name=req.guest_name, guest_contact=req.guest_contact,
        motivo=req.motivo, personas=req.personas, habitaciones=req.habitaciones,
        room_type_id=req.room_type_id, check_in=req.check_in.isoformat(),
        check_out=req.check_out.isoformat(), total_mxn=quote.total,
        next_followup=next_followup_date(req.check_in))
    crm_service.upsert_b2c(req.guest_name, req.guest_contact,
                           req.hotel_code, motivo=req.motivo)
    link = cloudbeds_service.payment_link(lead_id)
    pdf_path = pdf_service.generate_quote_pdf({
        "hotel_code": req.hotel_code, "reference": lead_id,
        "guest_name": req.guest_name, "guest_contact": req.guest_contact,
        "room_name": room["name"], "habitaciones": req.habitaciones,
        "personas": req.personas, "check_in": req.check_in.isoformat(),
        "check_out": req.check_out.isoformat(),
        "quote": quote.model_dump(), "payment_link": link,
    })
    return json.dumps({
        "lead_id": lead_id,
        "room": room["name"],
        "nights": quote.nights,
        "nightly_rate": format_mxn(quote.nightly_rate),
        "subtotal": format_mxn(quote.room_subtotal),
        "iva_16": format_mxn(quote.taxes),
        "total": format_mxn(quote.total),
        "payment_link": link,
        "pdf": pdf_path,
        "policies_hint": "Cancelación gratuita hasta 72 h antes del check-in.",
    }, ensure_ascii=False)


@tool
def create_reservation(lead_id: str) -> str:
    """Confirm an INDIVIDUAL reservation in Cloudbeds for an existing lead
    (the lead_id returned by send_individual_proposal). Call it ONLY after
    the guest explicitly accepts the proposal."""
    # Intercepted by the graph router — this body never executes.
    return "processed by pipeline"


@tool
def close_lead(lead_id: str, motivo: str) -> str:
    """Mark a lead as CLOSED LOST when the client rejects the proposal.
    motivo: short reason (precio, fechas, competencia...)."""
    ok = leads_service.close_lead(lead_id, won=False, notas=motivo)
    return "Lead marked CLOSED LOST." if ok else "Lead not found."


@tool
def submit_group_brief(hotel_code: str, contacto: str, correo: str,
                       tipo_evento: str, habitaciones: int, personas: int,
                       check_in: str, check_out: str, empresa: str = "",
                       servicios: str = "", room_type_id: str = "") -> str:
    """Submit the brief of a GROUP with rooms (5+ rooms or 15+ people).
    Triggers the automatic quote (occupancy-based discount), the internal
    human validation and the delivery of the proposal. Capture first: contact
    name, email, company (if any), event type, rooms, people, dates and
    required services. room_type_id optional (default: base category)."""
    # Intercepted by the graph router — this body never executes.
    return "processed by pipeline"


@tool
def create_group_reservation(lead_id: str) -> str:
    """Confirm a GROUP as CLOSED WON: creates the room block in Cloudbeds and
    notifies hotel + Ventas HQ. Call it ONLY when the group contact explicitly
    accepts the group proposal (lead_id starts with GR-)."""
    # Intercepted by the graph router — this body never executes.
    return "processed by pipeline"


@tool
def submit_event_brief(hotel_code: str, contacto: str, correo: str,
                       tipo_evento: str, personas: int, fecha: str,
                       servicios: str, empresa: str = "") -> str:
    """Register an EVENT WITHOUT rooms (venue, catering, AV, transfers...).
    Registers the lead, notifies the hotel supervision team (a human prepares
    that quote) and returns the extra catalog (tours, experiences) to offer."""
    try:
        brief = EventBrief(hotel_code=hotel_code, contacto=contacto,
                           correo=correo, empresa=empresa,
                           tipo_evento=tipo_evento, personas=personas,
                           fecha=_parse_date(fecha), servicios=servicios)
    except (ValidationError, ValueError) as exc:
        return f"Invalid event brief: {exc}"
    lead_id = leads_service.register_group_lead(
        brief.hotel_code, contacto=brief.contacto, empresa=brief.empresa,
        correo=brief.correo, tipo_evento=f"{brief.tipo_evento} (sin habitaciones)",
        habitaciones=0, personas=brief.personas,
        check_in=brief.fecha.isoformat(), check_out=brief.fecha.isoformat(),
        servicios=brief.servicios, occ_pct=0.0, descuento_pct=0.0,
        total_mxn=0.0, status=leads_service.STATUS_BRIEF,
        notas="Cotización de centros de consumo a cargo de supervisión del hotel")
    if brief.empresa:
        crm_service.upsert_b2b(brief.empresa, brief.contacto, brief.correo, brief.hotel_code)
    else:
        crm_service.upsert_b2c(brief.contacto, brief.correo, brief.hotel_code,
                               motivo=brief.tipo_evento)
    lead = leads_service.get_group_lead(lead_id)
    slack_service.notify_event_brief(lead)
    spaces = hotel_data_service.get_event_spaces(brief.hotel_code)
    upsells = hotel_data_service.get_upsells(brief.hotel_code)
    return json.dumps({
        "lead_id": lead_id,
        "status": ("Brief registrado. Supervisión del hotel prepara la cotización "
                   "de montaje/catering y te contacta hoy mismo."),
        "salones_disponibles": spaces,
        "catalogo_adicional": upsells,
    }, ensure_ascii=False, default=str)


@tool
def register_requirements(cloudbeds_id: str, requerimientos: str) -> str:
    """Save special requirements of a confirmed reservation (cuna, extra pax,
    early/late check-in, alergias...) and notify the hotel host so everything
    is ready 48 h before arrival."""
    if not cloudbeds_service.append_reservation_note(
            cloudbeds_id, f"Requerimientos: {requerimientos}"):
        return "Reservation not found in Cloudbeds."
    parts = cloudbeds_id.split("-")
    hotel_code = parts[1] if len(parts) >= 3 else ""
    slack_service.notify_host_requirements(cloudbeds_id, hotel_code,
                                           guest_name="huésped",
                                           check_in="(ver reserva)",
                                           requirements=requerimientos)
    return "Requirements saved and host notified (ready 48 h before arrival)."


@tool
def book_upsell(cloudbeds_id: str, upsell_name: str) -> str:
    """Attach an upsell (pick-up, tour, experience) to a confirmed reservation
    and notify the host, who confirms availability in max. 4 h."""
    if not cloudbeds_service.append_reservation_note(
            cloudbeds_id, f"Upsell: {upsell_name}"):
        return "Reservation not found in Cloudbeds."
    parts = cloudbeds_id.split("-")
    hotel_code = parts[1] if len(parts) >= 3 else ""
    slack_service.notify_upsell(cloudbeds_id, hotel_code,
                                guest_name="huésped", upsell=upsell_name)
    return "Upsell requested. The host will confirm within 4 hours."


@tool
def escalate_to_human(hotel_code: str, motivo: str, resumen: str,
                      lead_id: str = "") -> str:
    """Escalate the conversation to a human advisor. Use it for: rate
    negotiation, complex request unresolved after 2 attempts, complaint or
    incident, or no availability with flexible dates. resumen: 2-3 lines of
    context so the advisor can take over."""
    code = hotel_code.strip().upper()
    status = slack_service.notify_escalation(code, motivo, resumen)
    if lead_id:
        if lead_id.startswith("GR-"):
            leads_service.update_group_lead(lead_id, notas=f"Escalado: {motivo}")
        else:
            leads_service.update_individual_lead(
                lead_id, status=leads_service.STATUS_ESCALADO,
                notas=f"Escalado: {motivo}")
    return (f"Escalated to a human advisor ({status}). "
            "SLA: an advisor takes the case within 2 business hours.")


CHAT_TOOLS = [
    list_hotels, get_hotel_info, check_availability,
    send_individual_proposal, create_reservation, close_lead,
    submit_group_brief, create_group_reservation, submit_event_brief,
    register_requirements, book_upsell, escalate_to_human,
]
