"""Helpers shared by the chat channels (Telegram, WhatsApp).

Each channel maps one external conversation to one LangGraph thread and needs
the same plumbing: the singleton graph with SQLite persistence, LLM content
normalization, markdown table flattening (chat apps render no tables),
length-aware splitting, and detection of quote PDFs produced during a turn.
"""

import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage

from src.config.settings import CHECKPOINT_DB, PROJECT_ROOT

log = logging.getLogger("tasman.channels")

_graph = None


def get_graph():
    """Build the graph once; conversations survive restarts via SQLite."""
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


def text_content(content) -> str:
    """Normalize LLM message content (str or content-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        ).strip()
    return str(content)


def tables_to_lines(text: str) -> str:
    """Chat apps have no tables: flatten '| Concepto | Monto |' rows to lines."""
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


def split_text(text: str, max_len: int) -> list[str]:
    """Split a reply into channel-sized chunks, preferring newline breaks."""
    chunks = []
    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def new_pdfs(messages: list) -> list[Path]:
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
            payload = json.loads(text_content(m.content))
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
