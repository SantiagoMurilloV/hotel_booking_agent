"""LEADS working files: one table per hotel (Individuales) and
LEADS GRUPOS TASMAN (Grupos). The bot feeds 100% of opportunities here,
with status and automatic timestamps. Storage is Excel or Google Sheets
depending on STORAGE_BACKEND (see services/store.py)."""

from datetime import date, datetime

import pandas as pd

from src.config.settings import GROUP_LEADS_FILE, HOTELS, hotel_leads_file
from src.services import store

INDIVIDUAL_SHEET = "Individuales"
GROUP_SHEET = "Grupos"

# Pipeline statuses
STATUS_PROPUESTA = "PROPUESTA ENVIADA"
STATUS_SEGUIMIENTO = "SEGUIMIENTO"
STATUS_ESCALADO = "ESCALADO"
STATUS_BRIEF = "BRIEF CAPTURADO"
STATUS_WON = "CLOSED WON"
STATUS_LOST = "CLOSED LOST"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read(path, sheet: str) -> pd.DataFrame:
    return store.read_table(path, sheet)


def _write(df: pd.DataFrame, path, sheet: str) -> None:
    store.write_table(df, path, sheet)


# ------------------------------------------------------------ individuals

def register_individual_lead(hotel_code: str, *, guest_name: str,
                             guest_contact: str, motivo: str, personas: int,
                             habitaciones: int, room_type_id: str,
                             check_in: str, check_out: str, total_mxn: float,
                             next_followup: str, canal: str = "consola") -> str:
    lead_id = f"LD-{hotel_code}-{datetime.now().strftime('%y%m%d%H%M%S')}"
    row = {
        "lead_id": lead_id, "created_at": _now(), "canal": canal,
        "hotel": HOTELS[hotel_code], "guest_name": guest_name,
        "guest_contact": guest_contact, "motivo": motivo,
        "personas": personas, "habitaciones": habitaciones,
        "room_type_id": room_type_id, "check_in": check_in,
        "check_out": check_out, "total_mxn": total_mxn,
        "status": STATUS_PROPUESTA, "next_followup": next_followup,
        "followups_sent": 0, "last_update": _now(),
        "cloudbeds_id": "", "notas": "",
    }
    path = hotel_leads_file(hotel_code)
    df = _read(path, INDIVIDUAL_SHEET)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _write(df, path, INDIVIDUAL_SHEET)
    return lead_id


def update_individual_lead(lead_id: str, **fields) -> bool:
    hotel_code = _hotel_from_lead(lead_id)
    if hotel_code is None:
        return False
    path = hotel_leads_file(hotel_code)
    df = _read(path, INDIVIDUAL_SHEET)
    if df.empty or "lead_id" not in df.columns:
        return False
    mask = df["lead_id"] == lead_id
    if not mask.any():
        return False
    _apply_fields(df, mask, fields)
    _write(df, path, INDIVIDUAL_SHEET)
    return True


def _apply_fields(df: pd.DataFrame, mask, fields: dict) -> None:
    """Cell updates that survive pandas' strict dtypes (an empty column
    loads as float64 and rejects strings)."""
    fields = {**fields, "last_update": _now()}
    for key, value in fields.items():
        if isinstance(value, str) and key in df.columns:
            df[key] = df[key].astype("object")
        df.loc[mask, key] = value


def get_individual_lead(lead_id: str) -> dict | None:
    hotel_code = _hotel_from_lead(lead_id)
    if hotel_code is None:
        return None
    df = _read(hotel_leads_file(hotel_code), INDIVIDUAL_SHEET)
    if df.empty or "lead_id" not in df.columns:
        return None
    matches = df[df["lead_id"] == lead_id]
    if matches.empty:
        return None
    lead = matches.iloc[0].to_dict()
    lead["hotel_code"] = hotel_code
    return lead


def _hotel_from_lead(lead_id: str) -> str | None:
    parts = str(lead_id).split("-")
    return parts[1] if len(parts) >= 3 and parts[1] in HOTELS else None


def all_individual_leads() -> pd.DataFrame:
    frames = []
    for code in HOTELS:
        df = _read(hotel_leads_file(code), INDIVIDUAL_SHEET)
        if not df.empty:
            df["hotel_code"] = code
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def due_followups(today: date | None = None) -> list[dict]:
    """Open leads whose next_followup date has arrived."""
    today = today or date.today()
    df = all_individual_leads()
    if df.empty:
        return []
    open_mask = df["status"].isin([STATUS_PROPUESTA, STATUS_SEGUIMIENTO])
    due = []
    for _, row in df[open_mask].iterrows():
        nf = row.get("next_followup")
        if pd.isna(nf) or str(nf).strip() == "":
            continue
        if pd.to_datetime(nf).date() <= today:
            due.append(row.to_dict())
    return due


# ---------------------------------------------------------------- groups

def register_group_lead(hotel_code: str, *, contacto: str, empresa: str,
                        correo: str, tipo_evento: str, habitaciones: int,
                        personas: int, check_in: str, check_out: str,
                        servicios: str, occ_pct: float, descuento_pct: float,
                        total_mxn: float, status: str,
                        aprobado_por: str = "", canal: str = "consola",
                        notas: str = "") -> str:
    lead_id = f"GR-{hotel_code}-{datetime.now().strftime('%y%m%d%H%M%S')}"
    row = {
        "lead_id": lead_id, "created_at": _now(), "canal": canal,
        "hotel": HOTELS[hotel_code], "contacto": contacto, "empresa": empresa,
        "correo": correo, "tipo_evento": tipo_evento,
        "habitaciones": habitaciones, "personas": personas,
        "check_in": check_in, "check_out": check_out, "servicios": servicios,
        "occ_pct": occ_pct, "descuento_pct": descuento_pct,
        "total_mxn": total_mxn, "status": status,
        "aprobado_por": aprobado_por, "last_update": _now(),
        "cloudbeds_id": "", "notas": notas,
    }
    df = _read(GROUP_LEADS_FILE, GROUP_SHEET)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _write(df, GROUP_LEADS_FILE, GROUP_SHEET)
    return lead_id


def update_group_lead(lead_id: str, **fields) -> bool:
    df = _read(GROUP_LEADS_FILE, GROUP_SHEET)
    if df.empty or "lead_id" not in df.columns:
        return False
    mask = df["lead_id"] == lead_id
    if not mask.any():
        return False
    _apply_fields(df, mask, fields)
    _write(df, GROUP_LEADS_FILE, GROUP_SHEET)
    return True


def get_group_lead(lead_id: str) -> dict | None:
    df = _read(GROUP_LEADS_FILE, GROUP_SHEET)
    if df.empty or "lead_id" not in df.columns:
        return None
    matches = df[df["lead_id"] == lead_id]
    if matches.empty:
        return None
    lead = matches.iloc[0].to_dict()
    parts = lead_id.split("-")
    lead["hotel_code"] = parts[1] if len(parts) >= 3 else ""
    return lead


def all_group_leads() -> pd.DataFrame:
    return _read(GROUP_LEADS_FILE, GROUP_SHEET)


def close_lead(lead_id: str, won: bool, notas: str = "") -> bool:
    status = STATUS_WON if won else STATUS_LOST
    if str(lead_id).startswith("GR-"):
        return update_group_lead(lead_id, status=status, notas=notas)
    return update_individual_lead(lead_id, status=status, notas=notas,
                                  next_followup="")
