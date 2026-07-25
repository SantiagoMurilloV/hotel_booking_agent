"""CRM TASMAN (awareness): B2B and B2C tabs. The bot upserts every contact
it talks to, so Marketing owns a single client database. Storage is Excel or
Google Sheets depending on STORAGE_BACKEND (see services/store.py)."""

from datetime import datetime

import pandas as pd

from src.config.settings import CRM_FILE, HOTELS
from src.services import store

B2B_COLUMNS = ["empresa", "contacto", "correo", "hotel_interes", "origen",
               "created_at", "last_interaction", "notas"]
B2C_COLUMNS = ["nombre", "contacto", "hotel_interes", "motivo", "origen",
               "created_at", "last_interaction", "notas"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read(sheet: str, columns: list[str]) -> pd.DataFrame:
    df = store.read_table(CRM_FILE, sheet)
    return df if not df.empty else pd.DataFrame(columns=columns)


def upsert_b2c(nombre: str, contacto: str, hotel_code: str,
               motivo: str = "", origen: str = "bot", notas: str = "") -> None:
    df = _read("B2C", B2C_COLUMNS)
    mask = df["contacto"].astype(str).str.lower() == contacto.lower()
    if mask.any():
        df.loc[mask, ["last_interaction", "hotel_interes"]] = [_now(), HOTELS[hotel_code]]
    else:
        row = {"nombre": nombre, "contacto": contacto,
               "hotel_interes": HOTELS[hotel_code], "motivo": motivo,
               "origen": origen, "created_at": _now(),
               "last_interaction": _now(), "notas": notas}
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    store.write_table(df, CRM_FILE, "B2C")


def upsert_b2b(empresa: str, contacto: str, correo: str, hotel_code: str,
               origen: str = "bot", notas: str = "") -> None:
    df = _read("B2B", B2B_COLUMNS)
    mask = df["correo"].astype(str).str.lower() == correo.lower()
    if mask.any():
        df.loc[mask, ["last_interaction", "hotel_interes"]] = [_now(), HOTELS[hotel_code]]
    else:
        row = {"empresa": empresa, "contacto": contacto, "correo": correo,
               "hotel_interes": HOTELS[hotel_code], "origen": origen,
               "created_at": _now(), "last_interaction": _now(), "notas": notas}
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    store.write_table(df, CRM_FILE, "B2B")
