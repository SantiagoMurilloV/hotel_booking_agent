"""Cloudbeds mock: same interface the real API adapter will expose later
(availability, rates, occupancy, reservation creation, payment links).
Backed by output/cloudbeds_pms.xlsx so the client can inspect everything."""

from datetime import date, datetime, timedelta

import pandas as pd

from src.config.settings import PMS_FILE
from src.services import hotel_data_service


def _reservations() -> pd.DataFrame:
    if not PMS_FILE.exists():
        return pd.DataFrame(columns=["reservation_id", "hotel_code", "room_type_id",
                                     "rooms", "guest_name", "check_in", "check_out",
                                     "status", "source", "notes"])
    df = pd.read_excel(PMS_FILE, sheet_name="reservations")
    df = df[df["status"] == "confirmed"].copy()
    df["check_in"] = pd.to_datetime(df["check_in"]).dt.date
    df["check_out"] = pd.to_datetime(df["check_out"]).dt.date
    return df


def _overlapping(df: pd.DataFrame, hotel_code: str,
                 check_in: date, check_out: date) -> pd.DataFrame:
    return df[(df["hotel_code"] == hotel_code)
              & (df["check_in"] < check_out)
              & (df["check_out"] > check_in)]


def available_units(hotel_code: str, room_type_id: str,
                    check_in: date, check_out: date) -> int:
    """Minimum simultaneous availability of a room type across the stay."""
    room = hotel_data_service.get_room(hotel_code, room_type_id)
    if room is None:
        return 0
    bookings = _overlapping(_reservations(), hotel_code, check_in, check_out)
    bookings = bookings[bookings["room_type_id"] == room["room_type_id"]]
    quantity = int(room["quantity"])
    worst = 0
    day = check_in
    while day < check_out:
        busy = bookings[(bookings["check_in"] <= day) & (bookings["check_out"] > day)]
        worst = max(worst, int(busy["rooms"].sum()))
        day += timedelta(days=1)
    return quantity - worst


def availability_by_room(hotel_code: str, check_in: date,
                         check_out: date) -> list[dict]:
    """Availability and live rate per room type (what the real API returns)."""
    results = []
    for room in hotel_data_service.get_rooms(hotel_code):
        units = available_units(hotel_code, room["room_type_id"], check_in, check_out)
        results.append({
            "room_type_id": room["room_type_id"],
            "name": room["name"],
            "capacity": int(room["capacity"]),
            "beds": room["beds"],
            "rate_mxn": float(room["base_rate_mxn"]),
            "available_units": units,
            "amenities": room["amenities"],
        })
    return results


def get_occupancy(hotel_code: str, check_in: date, check_out: date) -> float:
    """OCC % of the hotel for the date range (booked room-nights / capacity)."""
    rooms = hotel_data_service.get_rooms(hotel_code)
    total_rooms = sum(int(r["quantity"]) for r in rooms)
    nights = (check_out - check_in).days
    if total_rooms == 0 or nights <= 0:
        return 0.0
    bookings = _overlapping(_reservations(), hotel_code, check_in, check_out)
    booked_nights = 0
    for _, b in bookings.iterrows():
        overlap = (min(b["check_out"], check_out) - max(b["check_in"], check_in)).days
        booked_nights += overlap * int(b["rooms"])
    return round(100.0 * booked_nights / (total_rooms * nights), 1)


def create_reservation(hotel_code: str, room_type_id: str, rooms: int,
                       guest_name: str, check_in: date, check_out: date,
                       notes: str = "", source: str = "bot") -> str:
    """Creates a confirmed reservation in the PMS. Returns the Cloudbeds ID."""
    reservation_id = f"CB-{hotel_code}-{datetime.now().strftime('%y%m%d%H%M%S')}"
    row = {
        "reservation_id": reservation_id,
        "hotel_code": hotel_code,
        "room_type_id": room_type_id.upper(),
        "rooms": rooms,
        "guest_name": guest_name,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "status": "confirmed",
        "source": source,
        "notes": notes,
    }
    if PMS_FILE.exists():
        df = pd.read_excel(PMS_FILE, sheet_name="reservations")
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        PMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([row])
    df.to_excel(PMS_FILE, sheet_name="reservations", index=False)
    return reservation_id


def append_reservation_note(reservation_id: str, note: str) -> bool:
    """Adds a note (requirements, upsells) to an existing reservation."""
    if not PMS_FILE.exists():
        return False
    df = pd.read_excel(PMS_FILE, sheet_name="reservations")
    mask = df["reservation_id"] == reservation_id
    if not mask.any():
        return False
    df["notes"] = df["notes"].astype("object").fillna("")
    current = df.loc[mask, "notes"].iloc[0]
    df.loc[mask, "notes"] = (f"{current} | {note}".strip(" |"))
    df.to_excel(PMS_FILE, sheet_name="reservations", index=False)
    return True


def payment_link(reference: str) -> str:
    """Mock payment link (the real one comes from Cloudbeds payments)."""
    return f"https://pay.tasman.mx/{reference}"
