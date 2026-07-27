"""Central configuration for the Tasman sales bot. The LLM lives behind
llm_factory so switching providers is an .env change, never a code change."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "src" / "data"
HOTELS_DIR = DATA_DIR / "hotels"
# Overridable so deploys can point it to a persistent volume (e.g. /data/output)
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_ROOT / "output"))
LEADS_DIR = OUTPUT_DIR / "leads"
QUOTES_DIR = OUTPUT_DIR / "cotizaciones"

# Working files (all Excel, as required by the client)
PMS_FILE = OUTPUT_DIR / "cloudbeds_pms.xlsx"          # Cloudbeds mock database
CRM_FILE = OUTPUT_DIR / "CRM TASMAN.xlsx"             # Awareness: B2B / B2C
GROUP_LEADS_FILE = LEADS_DIR / "LEADS GRUPOS TASMAN.xlsx"

# Hotel directory: code -> official name (one LEADS Excel per hotel)
HOTELS = {
    "AMINA": "AMINA WIND RESORT",
    "CALIZA": "CALIZA ROMA",
    "SAL": "CASA SAL",
    "TALAVERA": "CASA TALAVERA",
    "LAIVA": "LAIVA",
    "SANTA": "SANTA CASA",
}


def hotel_data_file(hotel_code: str) -> Path:
    """Ficha técnica (Excel) of a hotel."""
    return HOTELS_DIR / f"{HOTELS[hotel_code]}.xlsx"


def hotel_leads_file(hotel_code: str) -> Path:
    """LEADS individuales (Excel) of a hotel."""
    return LEADS_DIR / f"{HOTELS[hotel_code]}.xlsx"


# Business policy (Dirección de Ventas, flujo 2026)
GROUP_MIN_ROOMS = 5        # 5+ habitaciones  -> grupo
GROUP_MIN_PEOPLE = 15      # 15+ personas     -> grupo
DIRECTION_ROOMS = 15       # 15+ habitaciones -> notificar Dirección de Ventas

# OCC -> descuento (tabla del flujo de ventas)
OCC_DISCOUNTS = [
    (50, 20),   # OCC < 50%   -> 20% dto
    (70, 15),   # OCC 51-70%  -> 15% dto
    (90, 10),   # OCC 71-90%  -> 10% dto
]

TAX_RATE = 0.16  # IVA México
CURRENCY = "MXN"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# WhatsApp via Kapso (https://kapso.ai): sandbox for local testing, real
# number in production. The API mirrors Meta's Cloud API payloads.
KAPSO_API_KEY = os.getenv("KAPSO_API_KEY", "")
KAPSO_PHONE_NUMBER_ID = os.getenv("KAPSO_PHONE_NUMBER_ID", "")
KAPSO_WEBHOOK_SECRET = os.getenv("KAPSO_WEBHOOK_SECRET", "")
KAPSO_API_BASE = os.getenv("KAPSO_API_BASE",
                           "https://api.kapso.ai/meta/whatsapp/v24.0")
WHATSAPP_PORT = int(os.getenv("WHATSAPP_PORT", "8000"))

# LEADS/CRM storage: "excel" (local files) or "sheets" (Google Sheets)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "excel")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_KEY_PATH = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_KEY_PATH", str(PROJECT_ROOT / "service-account.json"))

# Hotel fact sheets (rates, rooms, policies, upsells): when set, they are read
# from this Google Sheet instead of src/data/hotels/*.xlsx
FICHAS_SHEET_ID = os.getenv("FICHAS_SHEET_ID", "")

# Service account credentials as inline JSON (for deploys without a key file).
# Takes precedence over GOOGLE_SERVICE_ACCOUNT_KEY_PATH when set.
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Telegram chat that validates group quotes (inline buttons). Empty -> console
# prompt when running interactively, auto-approve otherwise.
ADVISOR_CHAT_ID = os.getenv("ADVISOR_CHAT_ID", "")
ADVISOR_TIMEOUT_S = int(os.getenv("ADVISOR_TIMEOUT_S", "600"))

# LangGraph checkpointer database (conversations survive restarts)
CHECKPOINT_DB = os.getenv("CHECKPOINT_DB", str(OUTPUT_DIR / "checkpoints.sqlite"))


def llm_factory(temperature: float = 0.3):
    """Single point of LLM instantiation for the whole project."""
    from langchain.chat_models import init_chat_model

    return init_chat_model(
        LLM_MODEL,
        model_provider=LLM_PROVIDER,
        temperature=temperature,
    )
