"""Deterministic pricing: MXN, IVA 16%, and the OCC -> discount policy
table from Dirección de Ventas. Zero LLM involvement."""

from datetime import date

from src.config.settings import CURRENCY, OCC_DISCOUNTS, TAX_RATE
from src.models.schemas import Quote
from src.services import hotel_data_service


def discount_for_occ(occ_pct: float) -> int:
    """<50% -> 20 · 51-70% -> 15 · 71-90% -> 10 · >90% -> 0."""
    for threshold, discount in OCC_DISCOUNTS:
        if occ_pct <= threshold:
            return discount
    return 0


def build_quote(hotel_code: str, room_type_id: str, check_in: date,
                check_out: date, rooms: int, discount_pct: float = 0.0) -> Quote:
    room = hotel_data_service.get_room(hotel_code, room_type_id)
    if room is None:
        raise ValueError(f"Unknown room type {room_type_id} in {hotel_code}")
    nights = (check_out - check_in).days
    rate = float(room["base_rate_mxn"])
    room_subtotal = rate * nights * rooms
    discount_amount = round(room_subtotal * discount_pct / 100)
    taxed_base = room_subtotal - discount_amount
    taxes = round(taxed_base * TAX_RATE)
    return Quote(
        nights=nights,
        rooms=rooms,
        room_subtotal=room_subtotal,
        discount_pct=discount_pct,
        discount_amount=discount_amount,
        taxes=taxes,
        total=taxed_base + taxes,
        currency=CURRENCY,
        nightly_rate=rate,
    )


def format_mxn(amount: float) -> str:
    return f"${amount:,.0f} MXN"
