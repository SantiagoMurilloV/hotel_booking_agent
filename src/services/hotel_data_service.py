"""Read access to the fichas técnicas of the 6 hotels.

Source is either the local Excel workbooks (src/data/hotels/*.xlsx, default)
or — when FICHAS_SHEET_ID is set — a Google Sheet with 5 consolidated tabs
(HOTEL_INFO, ROOMS, POLICIES, UPSELLS, EVENT_SPACES), each carrying a
hotel_code column. The sheet lets the hotel team edit rates, rooms and
policies from Drive; edits go live within FICHAS_CACHE_TTL seconds without
restarting the bot.
"""

import time
from functools import lru_cache

import pandas as pd

from src.config.settings import FICHAS_SHEET_ID, HOTELS, hotel_data_file

FICHAS_CACHE_TTL = 300  # seconds

_cache: dict[str, tuple[float, pd.DataFrame]] = {}


# ------------------------------------------------------------ excel source

@lru_cache(maxsize=8)
def _workbook(hotel_code: str) -> dict[str, pd.DataFrame]:
    return pd.read_excel(hotel_data_file(hotel_code), sheet_name=None)


# ----------------------------------------------------------- sheets source

def _sheet_df(tab: str) -> pd.DataFrame:
    now = time.time()
    hit = _cache.get(tab)
    if hit and now - hit[0] < FICHAS_CACHE_TTL:
        return hit[1]
    from src.services import store
    df = store._sheets_read(tab, sheet_id=FICHAS_SHEET_ID)
    _cache[tab] = (now, df)
    return df


def _sheet_rows(tab: str, hotel_code: str) -> list[dict] | None:
    """Rows of a consolidated tab for one hotel; None -> fall back to Excel."""
    if not FICHAS_SHEET_ID:
        return None
    df = _sheet_df(tab)
    if df.empty or "hotel_code" not in df.columns:
        return None
    rows = df[df["hotel_code"] == hotel_code]
    if rows.empty:
        return None
    return rows.drop(columns=["hotel_code"]).to_dict(orient="records")


# ------------------------------------------------------------- public API

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
    rows = _sheet_rows("HOTEL_INFO", hotel_code)
    if rows:
        return rows[0]
    df = _workbook(hotel_code)["hotel_info"]
    return dict(zip(df["key"], df["value"]))


def get_rooms(hotel_code: str) -> list[dict]:
    rows = _sheet_rows("ROOMS", hotel_code)
    if rows is not None:
        return rows
    return _workbook(hotel_code)["rooms"].to_dict(orient="records")


def get_room(hotel_code: str, room_type_id: str) -> dict | None:
    matches = [r for r in get_rooms(hotel_code)
               if str(r["room_type_id"]).upper() == room_type_id.upper()]
    return matches[0] if matches else None


def get_policies(hotel_code: str) -> list[dict]:
    rows = _sheet_rows("POLICIES", hotel_code)
    if rows is not None:
        return rows
    return _workbook(hotel_code)["policies"].to_dict(orient="records")


def get_upsells(hotel_code: str) -> list[dict]:
    rows = _sheet_rows("UPSELLS", hotel_code)
    if rows is not None:
        return rows
    return _workbook(hotel_code)["upsells"].to_dict(orient="records")


def get_event_spaces(hotel_code: str) -> list[dict]:
    rows = _sheet_rows("EVENT_SPACES", hotel_code)
    if rows is not None:
        return rows
    return _workbook(hotel_code)["event_spaces"].to_dict(orient="records")
