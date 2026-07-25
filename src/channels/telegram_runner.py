"""Telegram channel for the Tasman sales bot.

Every Telegram chat maps to its own LangGraph thread (thread_id = chat id),
so each user who writes to the bot gets an isolated conversation with its own
state — no per-user setup needed: identity comes in every update payload.

Group-quote validations (LangGraph interrupt) are resolved, in order of
preference:
1. ADVISOR_CHAT_ID set  -> sent to that Telegram chat with inline buttons
   (approve / reject / adjust discount). Times out to auto-approve after
   ADVISOR_TIMEOUT_S so the client never hangs.
2. Interactive terminal -> console prompt (same UX as `python -m src.main`).
3. Otherwise            -> auto-approve with an audit note (headless deploys
   without an advisor configured).

Conversations survive restarts via a SQLite checkpointer (CHECKPOINT_DB).
Slack team notifications are untouched: they fire inside the graph nodes
after the advisor's decision, exactly as in the console version.

Run:  python -m src.channels.telegram_runner
"""

import asyncio
import html
import itertools
import json
import logging
import re
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from src.config.settings import (ADVISOR_CHAT_ID, ADVISOR_TIMEOUT_S,
                                 CHECKPOINT_DB, HOTELS_DIR, PROJECT_ROOT,
                                 TELEGRAM_BOT_TOKEN)
from src.main import _ask_advisor

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tasman.telegram")

TELEGRAM_MAX_LEN = 4096

WELCOME = (
    "🛎️ ¡Hola{name}! Soy el asistente de reservas de los hoteles TASMAN: "
    "Amina Wind Resort, Caliza Roma, Casa Sal, Casa Talavera, Laiva y "
    "Santa Casa.\n\n¿En qué puedo ayudarte? Puedo cotizar tu estancia, "
    "grupos y eventos al instante."
)

_graph = None
_advisor_lock = asyncio.Lock()            # one console validation at a time
_chat_locks: dict[int, asyncio.Lock] = {} # per-chat message ordering
_pending: dict[str, asyncio.Future] = {}  # validation id -> advisor decision
_validation_ids = itertools.count(1)


def _get_graph():
    global _graph
    if _graph is None:
        from src.orchestrator.graph import build_graph
        checkpointer = None
        try:
            import sqlite3

            from langgraph.checkpoint.sqlite import SqliteSaver
            Path(CHECKPOINT_DB).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
            checkpointer = SqliteSaver(conn)
            log.info("SQLite checkpointer: %s", CHECKPOINT_DB)
        except ImportError:
            log.warning("langgraph-checkpoint-sqlite not installed — "
                        "conversations won't survive restarts")
        _graph = build_graph(checkpointer)
    return _graph


def _lock_for(chat_id: int) -> asyncio.Lock:
    return _chat_locks.setdefault(chat_id, asyncio.Lock())


# ------------------------------------------------------------- formatting

def _text(content) -> str:
    """Normalize LLM message content (str or content-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        ).strip()
    return str(content)


def _tables_to_lines(text: str) -> str:
    """Telegram has no tables: flatten '| Concepto | Monto |' rows to lines."""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row |---|---|
            cells = [c for c in cells if c]
            if len(cells) == 2:
                out.append(f"{cells[0]}: {cells[1]}")
            else:
                out.append(" · ".join(cells))
        else:
            out.append(line)
    return "\n".join(out)


def _md_to_telegram_html(text: str) -> str:
    """Render the LLM's markdown as Telegram HTML (bold/italic/code/bullets)."""
    text = _tables_to_lines(text)
    text = re.sub(r"^\s*([-_*])\1{2,}\s*$", "", text, flags=re.MULTILINE)  # --- hr
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                  r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)
    # single *italic*, avoiding list markers like "* item"
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse gaps left by removed rules
    return text


async def _reply(update: Update, chunk: str) -> None:
    """Send one chunk with Telegram formatting; fall back to plain text."""
    try:
        await update.message.reply_text(_md_to_telegram_html(chunk),
                                        parse_mode=ParseMode.HTML)
    except BadRequest:
        await update.message.reply_text(chunk)


def _split(text: str) -> list[str]:
    """Split a reply into Telegram-sized chunks, preferring newline breaks."""
    chunks = []
    while len(text) > TELEGRAM_MAX_LEN:
        cut = text.rfind("\n", 0, TELEGRAM_MAX_LEN)
        if cut < TELEGRAM_MAX_LEN // 2:
            cut = TELEGRAM_MAX_LEN
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def _new_pdfs(messages: list) -> list[Path]:
    """PDF paths produced by tools during the last turn (after the last human msg)."""
    last_human = 0
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last_human = i
    pdfs = []
    for m in messages[last_human:]:
        if not isinstance(m, ToolMessage):
            continue
        try:
            payload = json.loads(_text(m.content))
        except (json.JSONDecodeError, TypeError):
            continue
        pdf = payload.get("pdf") if isinstance(payload, dict) else None
        if pdf:
            path = Path(pdf)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if path.exists():
                pdfs.append(path)
    return pdfs


# ------------------------------------------------- advisor validation flow

def _format_validation(payload: dict) -> str:
    lines = ["🔒 VALIDACIÓN — cotización de grupo", ""]
    for key in ("hotel", "contacto", "empresa", "tipo_evento",
                "habitaciones", "personas", "fechas", "room_type"):
        lines.append(f"{key.replace('_', ' ').capitalize()}: {payload.get(key)}")
    lines.append(f"OCC del hotel: {payload.get('occ_pct')}%")
    lines.append(f"Dto. por OCC: {payload.get('descuento_pct')}%")
    if payload.get("nota_direccion"):
        lines.append(payload["nota_direccion"])
    lines.append("")
    lines.append("Cotización:")
    for concepto, valor in payload.get("cotizacion", {}).items():
        lines.append(f"  • {concepto.replace('_', ' ')}: {valor}")
    return "\n".join(lines)


async def _ask_advisor_telegram(bot, payload: dict) -> dict:
    """Send the validation card to the advisor chat and await their tap."""
    vid = f"v{next(_validation_ids)}"
    fut = asyncio.get_running_loop().create_future()
    _pending[vid] = fut
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aprobar", callback_data=f"{vid}:aprobar"),
         InlineKeyboardButton("❌ Rechazar", callback_data=f"{vid}:rechazar")],
        [InlineKeyboardButton(f"✏️ dto {d}%", callback_data=f"{vid}:dto:{d}")
         for d in (5, 10, 15, 20)],
    ])
    await bot.send_message(chat_id=ADVISOR_CHAT_ID,
                           text=_format_validation(payload),
                           reply_markup=keyboard)
    log.info("🔒 Validación %s enviada al asesor (chat %s)", vid, ADVISOR_CHAT_ID)
    try:
        return await asyncio.wait_for(fut, timeout=ADVISOR_TIMEOUT_S)
    except asyncio.TimeoutError:
        _pending.pop(vid, None)
        log.warning("⏰ Validación %s sin respuesta — auto-aprobada", vid)
        return {"decision": "aprobar",
                "asesor": f"auto-aprobado (asesor sin responder en {ADVISOR_TIMEOUT_S}s)"}


async def on_advisor_decision(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    vid, _, action = query.data.partition(":")
    fut = _pending.pop(vid, None)
    if fut is None or fut.done():
        await query.answer("Esta validación ya fue resuelta.")
        return

    asesor = query.from_user.first_name or "Asesor Tasman"
    if action == "aprobar":
        decision = {"decision": "aprobar", "asesor": f"{asesor} (Telegram)"}
        label = "✅ Aprobada"
    elif action == "rechazar":
        decision = {"decision": "rechazar", "nota": "rechazado por asesor",
                    "asesor": f"{asesor} (Telegram)"}
        label = "❌ Rechazada"
    else:  # dto:<n>
        pct = float(action.split(":")[1])
        decision = {"decision": "ajustar", "descuento": pct,
                    "asesor": f"{asesor} (Telegram)",
                    "nota": f"Descuento ajustado a {pct:.0f}%"}
        label = f"✏️ Descuento ajustado a {pct:.0f}%"

    fut.set_result(decision)
    await query.answer("Decisión registrada")
    try:
        await query.edit_message_text(
            f"{query.message.text}\n\n➡️ {label} por {asesor}")
    except BadRequest:
        pass
    log.info("🔒 Validación %s: %s por %s", vid, label, asesor)


async def _resolve_interrupt(bot, payload: dict) -> dict:
    if ADVISOR_CHAT_ID:
        return await _ask_advisor_telegram(bot, payload)
    if sys.stdin.isatty():
        async with _advisor_lock:
            return await asyncio.to_thread(_ask_advisor, payload)
    log.warning("Sin ADVISOR_CHAT_ID ni consola — cotización auto-aprobada")
    return {"decision": "aprobar", "asesor": "auto-aprobado (sin asesor configurado)"}


# ------------------------------------------------------------- handlers

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = f", {user.first_name}" if user and user.first_name else ""
    log.info("nuevo /start de chat_id=%s (%s)", update.effective_chat.id,
             user.first_name if user else "?")
    await update.message.reply_text(WELCOME.format(name=name))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    user = update.effective_user
    log.info("📥 [%s | %s] %s", chat_id, user.first_name if user else "?", text)

    config = {"configurable": {"thread_id": f"tg-{chat_id}"}}
    graph = _get_graph()

    async with _lock_for(chat_id):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            result = await asyncio.to_thread(
                graph.invoke, {"messages": [HumanMessage(content=text)]}, config)

            while result.get("__interrupt__"):
                await update.message.reply_text(
                    "⏳ Un momento por favor — un asesor Tasman está validando tu "
                    "cotización de grupo...")
                decision = await _resolve_interrupt(
                    context.bot, result["__interrupt__"][0].value)
                await context.bot.send_chat_action(chat_id=chat_id,
                                                   action=ChatAction.TYPING)
                result = await asyncio.to_thread(
                    graph.invoke, Command(resume=decision), config)
        except Exception:
            log.exception("Error procesando mensaje de chat_id=%s", chat_id)
            await update.message.reply_text(
                "Lo siento, tuve un problema técnico procesando tu mensaje. "
                "¿Puedes intentarlo de nuevo?")
            return

        reply = _text(result["messages"][-1].content).strip()
        log.info("📤 [%s] %s", chat_id, reply[:200])
        for chunk in _split(reply or "..."):
            await _reply(update, chunk)

        # Attach any quote PDF generated during this turn
        for pdf in _new_pdfs(result["messages"]):
            try:
                await context.bot.send_document(chat_id=chat_id,
                                                document=pdf.open("rb"),
                                                filename=pdf.name,
                                                caption="📄 Tu cotización Tasman")
                log.info("📎 [%s] PDF enviado: %s", chat_id, pdf.name)
            except Exception:
                log.exception("No se pudo enviar el PDF %s", pdf)


async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Por ahora solo entiendo mensajes de texto 🙂 "
            "Cuéntame qué hotel o fechas te interesan.")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")

    if not HOTELS_DIR.exists() or not any(HOTELS_DIR.glob("*.xlsx")):
        print("Datos Tasman no encontrados. Generándolos primero...")
        from src.data.generate_tasman_data import main as generate_data
        generate_data()

    _get_graph()  # build once at startup (fail fast if LLM config is wrong)

    app = (Application.builder()
           .token(TELEGRAM_BOT_TOKEN)
           .concurrent_updates(True)   # advisor taps must not wait behind chats
           .build())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_advisor_decision))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(~filters.TEXT, on_other))

    print("=" * 60)
    print("  TASMAN — Bot de ventas · canal Telegram (long polling)")
    if ADVISOR_CHAT_ID:
        print(f"  Validaciones de grupo → Telegram chat {ADVISOR_CHAT_ID}")
    else:
        print("  Validaciones de grupo → esta consola (o auto si headless)")
    print("  Ctrl+C para detener.")
    print("=" * 60)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
