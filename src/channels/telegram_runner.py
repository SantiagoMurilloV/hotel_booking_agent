"""Telegram channel for the Tasman sales bot.

Every Telegram chat maps to its own LangGraph thread (thread_id = chat id),
so each user who writes to the bot gets an isolated conversation with its own
state — no per-user setup needed: identity comes in every update payload.

Group-quote validations (LangGraph interrupt) are answered by the Tasman
advisor in THIS console, same UX as `python -m src.main`. While the advisor
decides, the client sees a "estamos validando" message in Telegram.

Run:  python -m src.channels.telegram_runner
"""

import asyncio
import html
import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from src.config.settings import HOTELS_DIR, PROJECT_ROOT, TELEGRAM_BOT_TOKEN
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
_advisor_lock = asyncio.Lock()   # one console validation at a time


def _get_graph():
    global _graph
    if _graph is None:
        from src.orchestrator.graph import build_graph
        _graph = build_graph()
    return _graph


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

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        result = await asyncio.to_thread(
            graph.invoke, {"messages": [HumanMessage(content=text)]}, config)

        while result.get("__interrupt__"):
            await update.message.reply_text(
                "⏳ Un momento por favor — un asesor Tasman está validando tu "
                "cotización de grupo...")
            async with _advisor_lock:
                decision = await asyncio.to_thread(
                    _ask_advisor, result["__interrupt__"][0].value)
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
            await context.bot.send_document(chat_id=chat_id, document=pdf.open("rb"),
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

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(~filters.TEXT, on_other))

    print("=" * 60)
    print("  TASMAN — Bot de ventas · canal Telegram (long polling)")
    print("  Las validaciones de grupo se responden en ESTA consola.")
    print("  Ctrl+C para detener.")
    print("=" * 60)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
