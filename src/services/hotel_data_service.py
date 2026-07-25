"""Read access to the fichas técnicas (one Excel per hotel)."""

from functools import lru_cache

import pandas as pd

from src.config.settings import HOTELS, hotel_data_file


@lru_cache(maxsize=8)
def _workbook(hotel_code: str) -> dict[str, pd.DataFrame]:
    return pd.read_excel(hotel_data_file(hotel_code), sheet_name=None)


def hotel_directory() -> list[dict]:
    """Compact card of every hotel in the group (for cross-recommendation)."""
    cards = []
    for code in HOTELS:
        info = get_hotel_info(code)
        cards.append({
            "hotel_code": code,
            "name": info["name"],
            "destino": info["destino"],
            "categoria": info["categoria"],
            "descripcion": info["descripcion"],
        })
    return cards


def get_hotel_info(hotel_code: str) -> dict:
    df = _workbook(hotel_code)["hotel_info"]
    return dict(zip(df["key"], df["value"]))


def get_rooms(hotel_code: str) -> list[dict]:
    return _workbook(hotel_code)["rooms"].to_dict(orient="records")


def get_room(hotel_code: str, room_type_id: str) -> dict | None:
    matches = [r for r in get_rooms(hotel_code)
               if r["room_type_id"] == room_type_id.upper()]
    return matches[0] if matches else None


def get_policies(hotel_code: str) -> list[dict]:
    return _workbook(hotel_code)["policies"].to_dict(orient="records")


def get_upsells(hotel_code: str) -> list[dict]:
    return _workbook(hotel_code)["upsells"].to_dict(orient="records")


def get_event_spaces(hotel_code: str) -> list[dict]:
    return _workbook(hotel_code)["event_spaces"].to_dict(orient="records")
