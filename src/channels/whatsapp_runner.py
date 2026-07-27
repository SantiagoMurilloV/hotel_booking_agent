"""WhatsApp channel for the Tasman sales bot, via Kapso (https://kapso.ai).

Kapso wraps Meta's WhatsApp Cloud API: inbound messages arrive as webhooks
(event `whatsapp.message.received`) and replies go out through a REST call
authenticated with X-API-Key. Every WhatsApp phone maps to its own LangGraph
thread (thread_id = wa-<phone>) — same isolation model as the Telegram channel.

Local testing with the Kapso sandbox:
1. Kapso dashboard -> WhatsApp -> Sandbox -> Add Test Number (your phone),
   then send the 6-char activation code to the sandbox number.
2. Copy the sandbox API key and phone number id into .env
   (KAPSO_API_KEY, KAPSO_PHONE_NUMBER_ID).
3. Run this server:   python -m src.channels.whatsapp_runner
4. Expose it:         ngrok http 8000   (or: cloudflared tunnel --url http://localhost:8000)
5. Sandbox -> Manage Webhooks: register  https://<tunnel>/kapso/webhook  for
   whatsapp.message.received. If you set a secret there, mirror it in
   KAPSO_WEBHOOK_SECRET so signatures are verified.
6. Write to the sandbox number from your phone.

Kapso requires a 200 within 10 seconds, so the webhook only enqueues the
message and the graph runs in a background task. Group-quote validations
(LangGraph interrupt) are resolved in this console when the terminal is
interactive (same UX as `python -m src.main`), otherwise they auto-approve
with an audit note. Sandbox caveat: only text/interactive messages are
supported, so quote PDFs fall back to a text notice if the upload fails.

Run:  python -m src.channels.whatsapp_runner
"""

import asyncio
import hashlib
import hmac
import logging
import sys
from collections import OrderedDict
from pathlib import Path
import re

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.channels.common import (get_graph, new_pdfs, split_text,
                                 tables_to_lines, text_content)
from src.config.settings import (HOTELS_DIR, KAPSO_API_BASE, KAPSO_API_KEY,
                                 KAPSO_PHONE_NUMBER_ID, KAPSO_WEBHOOK_SECRET,
                                 WHATSAPP_PORT)
from src.main import _ask_advisor

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tasman.whatsapp")

WHATSAPP_MAX_LEN = 4096

app = FastAPI(title="Tasman WhatsApp channel (Kapso)")

_client: httpx.AsyncClient | None = None
_advisor_lock = asyncio.Lock()             # one console validation at a time
_chat_locks: dict[str, asyncio.Lock] = {}  # per-phone message ordering
_seen_ids: OrderedDict[str, None] = OrderedDict()  # dedupe webhook retries
_SEEN_MAX = 1000


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=f"{KAPSO_API_BASE}/{KAPSO_PHONE_NUMBER_ID}",
            headers={"X-API-Key": KAPSO_API_KEY},
            timeout=30,
        )
    return _client


def _lock_for(phone: str) -> asyncio.Lock:
    return _chat_locks.setdefault(phone, asyncio.Lock())


def _is_duplicate(message_id: str) -> bool:
    if not message_id or message_id in _seen_ids:
        return bool(message_id)
    _seen_ids[message_id] = None
    while len(_seen_ids) > _SEEN_MAX:
        _seen_ids.popitem(last=False)
    return False


# ------------------------------------------------------------- formatting

def _md_to_whatsapp(text: str) -> str:
    """Render the LLM's markdown with WhatsApp formatting (*bold*, bullets)."""
    text = tables_to_lines(text)
    text = re.sub(r"^\s*([-_*])\1{2,}\s*$", "", text, flags=re.MULTILINE)  # --- hr
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1: \2", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)-\s+", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ------------------------------------------------------------- Kapso API

async def _send_text(to: str, body: str) -> None:
    for chunk in split_text(body or "...", WHATSAPP_MAX_LEN):
        r = await _http().post("/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": chunk},
        })
        if r.status_code >= 400:
            log.error("Kapso rechazó el envío a %s: %s %s",
                      to, r.status_code, r.text[:300])


async def _mark_read_typing(message_id: str) -> None:
    """Read receipt + typing indicator; best-effort (sandbox may ignore it)."""
    try:
        await _http().post("/messages", json={
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        })
    except httpx.HTTPError as exc:
        log.debug("typing indicator falló: %s", exc)


async def _send_pdf(to: str, pdf: Path) -> None:
    """Upload the quote PDF and send it as a document; text notice on failure."""
    try:
        with pdf.open("rb") as fh:
            up = await _http().post(
                "/media",
                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                files={"file": (pdf.name, fh, "application/pdf")},
            )
        up.raise_for_status()
        media_id = up.json()["id"]
        r = await _http().post("/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {"id": media_id, "filename": pdf.name,
                         "caption": "📄 Tu cotización Tasman"},
        })
        r.raise_for_status()
        log.info("📎 [%s] PDF enviado: %s", to, pdf.name)
    except (httpx.HTTPError, KeyError):
        log.warning("No se pudo adjuntar el PDF %s (¿sandbox?); aviso por texto",
                    pdf.name, exc_info=True)
        await _send_text(
            to, f"📄 Generé tu cotización en PDF ({pdf.name}). En este canal "
                "de pruebas no puedo adjuntarla, pero queda lista para enviártela.")


# ------------------------------------------------- advisor validation flow

async def _resolve_interrupt(payload: dict) -> dict:
    if sys.stdin.isatty():
        async with _advisor_lock:
            return await asyncio.to_thread(_ask_advisor, payload)
    log.warning("Sin consola interactiva — cotización auto-aprobada")
    return {"decision": "aprobar", "asesor": "auto-aprobado (sin asesor configurado)"}


# ------------------------------------------------------------- webhook

def _signature_ok(raw: bytes, header: str | None) -> bool:
    if not KAPSO_WEBHOOK_SECRET:
        return True  # no secret configured -> accept (local testing)
    if not header:
        return False
    digest = hmac.new(KAPSO_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header.strip())


def _inbound_messages(payload: dict) -> list[dict]:
    """Flatten single or batched Kapso webhook payloads to message dicts."""
    if payload.get("batch") and isinstance(payload.get("data"), list):
        items = payload["data"]
    elif isinstance(payload.get("data"), dict):
        items = [payload["data"]]
    else:
        items = [payload]
    messages = []
    for item in items:
        msg = item.get("message")
        if not isinstance(msg, dict):
            continue
        if (msg.get("kapso") or {}).get("direction", "inbound") != "inbound":
            continue  # ignore echoes of our own sends
        messages.append(msg)
    return messages


async def _handle_message(msg: dict) -> None:
    phone = msg.get("from") or ""
    mid = msg.get("id") or ""
    if not phone:
        log.warning("Mensaje sin remitente, ignorado: %s", msg)
        return

    if msg.get("type") != "text":
        await _send_text(phone, "Por ahora solo entiendo mensajes de texto 🙂 "
                                "Cuéntame qué hotel o fechas te interesan.")
        return

    text = (msg.get("text") or {}).get("body", "").strip()
    if not text:
        return
    log.info("📥 [%s] %s", phone, text)

    config = {"configurable": {"thread_id": f"wa-{phone}"}}
    graph = get_graph()

    async with _lock_for(phone):
        await _mark_read_typing(mid)
        try:
            result = await asyncio.to_thread(
                graph.invoke, {"messages": [HumanMessage(content=text)]}, config)

            while result.get("__interrupt__"):
                await _send_text(
                    phone, "⏳ Un momento por favor — un asesor Tasman está "
                           "validando tu cotización de grupo...")
                decision = await _resolve_interrupt(result["__interrupt__"][0].value)
                result = await asyncio.to_thread(
                    graph.invoke, Command(resume=decision), config)
        except Exception:
            log.exception("Error procesando mensaje de %s", phone)
            await _send_text(phone, "Lo siento, tuve un problema técnico "
                                    "procesando tu mensaje. ¿Puedes intentarlo "
                                    "de nuevo?")
            return

        reply = text_content(result["messages"][-1].content).strip()
        log.info("📤 [%s] %s", phone, reply[:200])
        await _send_text(phone, _md_to_whatsapp(reply))

        for pdf in new_pdfs(result["messages"]):
            await _send_pdf(phone, pdf)


@app.get("/")
async def health() -> dict:
    return {"status": "ok", "channel": "whatsapp", "provider": "kapso"}


@app.post("/kapso/webhook")
async def kapso_webhook(request: Request) -> Response:
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("X-Webhook-Signature")):
        log.warning("Firma de webhook inválida — rechazado")
        return Response(status_code=401)

    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=400)

    # ACK fast (Kapso expects 200 within 10s); the graph runs in the background
    for msg in _inbound_messages(payload):
        if _is_duplicate(msg.get("id") or ""):
            log.info("Webhook duplicado ignorado: %s", msg.get("id"))
            continue
        asyncio.get_running_loop().create_task(_handle_message(msg))
    return Response(status_code=200)


def main() -> None:
    missing = [name for name, value in
               (("KAPSO_API_KEY", KAPSO_API_KEY),
                ("KAPSO_PHONE_NUMBER_ID", KAPSO_PHONE_NUMBER_ID)) if not value]
    if missing:
        raise SystemExit(f"Falta {', '.join(missing)} en .env")

    if not HOTELS_DIR.exists() or not any(HOTELS_DIR.glob("*.xlsx")):
        print("Datos Tasman no encontrados. Generándolos primero...")
        from src.data.generate_tasman_data import main as generate_data
        generate_data()

    get_graph()  # build once at startup (fail fast if LLM config is wrong)

    print("=" * 60)
    print("  TASMAN — Bot de ventas · canal WhatsApp (Kapso webhooks)")
    print(f"  Escuchando en http://0.0.0.0:{WHATSAPP_PORT}/kapso/webhook")
    print("  Exponlo con:  ngrok http " + str(WHATSAPP_PORT))
    if KAPSO_WEBHOOK_SECRET:
        print("  Verificación de firma: activada")
    else:
        print("  Verificación de firma: desactivada (KAPSO_WEBHOOK_SECRET vacío)")
    print("  Validaciones de grupo → esta consola (o auto si headless)")
    print("  Ctrl+C para detener.")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=WHATSAPP_PORT, log_level="info")


if __name__ == "__main__":
    main()
