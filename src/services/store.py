"""Tabular storage for LEADS and CRM data: local Excel or Google Sheets.

STORAGE_BACKEND=excel  -> original output/*.xlsx files (default)
STORAGE_BACKEND=sheets -> one Google spreadsheet (GOOGLE_SHEET_ID), one tab
                          per table: CRM_B2B, CRM_B2C, LEADS_GRUPOS and
                          LEADS_<hotel> — created automatically on first write.

The other Excel files stay local on purpose: the hotel fichas técnicas
(src/data/hotels) and the PMS mock (output/cloudbeds_pms.xlsx) are mock data
sources that a later phase replaces with the real Cloudbeds API.
"""

from pathlib import Path

import pandas as pd

from src.config.settings import (CRM_FILE, GOOGLE_SERVICE_ACCOUNT_KEY_PATH,
                                 GOOGLE_SHEET_ID, GROUP_LEADS_FILE,
                                 STORAGE_BACKEND)


def _tab_name(path: Path, sheet: str) -> str:
    """Worksheet title in the spreadsheet for an (excel path, sheet) pair."""
    path = Path(path)
    if path == CRM_FILE:
        return f"CRM_{sheet}"            # CRM_B2B / CRM_B2C
    if path == GROUP_LEADS_FILE:
        return "LEADS_GRUPOS"
    return f"LEADS_{path.stem}"          # LEADS_LAIVA, LEADS_CASA SAL, ...


def _cell(v):
    if pd.isna(v):
        return ""
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


# ------------------------------------------------------------------ sheets

_spreadsheet = None


def _open_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        import gspread
        if not GOOGLE_SHEET_ID:
            raise RuntimeError(
                "STORAGE_BACKEND=sheets requires GOOGLE_SHEET_ID in .env")
        key_path = Path(GOOGLE_SERVICE_ACCOUNT_KEY_PATH)
        if not key_path.exists():
            raise RuntimeError(
                f"Service account key not found at {key_path}. Download the "
                "JSON key from Google Cloud and point "
                "GOOGLE_SERVICE_ACCOUNT_KEY_PATH to it.")
        gc = gspread.service_account(filename=str(key_path))
        _spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
    return _spreadsheet


def _sheets_read(tab: str) -> pd.DataFrame:
    import gspread
    try:
        ws = _open_spreadsheet().worksheet(tab)
    except gspread.WorksheetNotFound:
        return pd.DataFrame()
    return pd.DataFrame(ws.get_all_records())


def _sheets_write(df: pd.DataFrame, tab: str) -> None:
    import gspread
    ss = _open_spreadsheet()
    try:
        ws = ss.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=tab, rows=max(len(df) + 10, 50),
                              cols=max(len(df.columns) + 2, 20))
    values = [df.columns.tolist()] + df.map(_cell).values.tolist()
    ws.clear()
    ws.update(values, value_input_option="RAW")


# ------------------------------------------------------------------- excel

def _excel_read(path: Path, sheet: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except ValueError:               # workbook exists but the sheet doesn't
        return pd.DataFrame()


def _excel_write(df: pd.DataFrame, path: Path, sheet: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = pd.read_excel(path, sheet_name=None) if path.exists() else {}
    sheets[sheet] = df
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)


# ------------------------------------------------------------- public API

def read_table(path, sheet: str) -> pd.DataFrame:
    """Read a table; returns an empty DataFrame if it doesn't exist yet."""
    if STORAGE_BACKEND == "sheets":
        return _sheets_read(_tab_name(path, sheet))
    return _excel_read(path, sheet)


def write_table(df: pd.DataFrame, path, sheet: str) -> None:
    if STORAGE_BACKEND == "sheets":
        _sheets_write(df, _tab_name(path, sheet))
    else:
        _excel_write(df, path, sheet)
