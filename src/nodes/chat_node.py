from langchain_core.messages import trim_messages

from src.agents.concierge_agent import build_agent, system_message

MAX_HISTORY_MESSAGES = 40

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def chat_node(state: dict) -> dict:
    history = trim_messages(
        state["messages"],
        max_tokens=MAX_HISTORY_MESSAGES,
        token_counter=len,          # count messages, not tokens
        strategy="last",
        start_on="human",           # never start mid tool-call exchange
        include_system=False,       # system prompt is prepended separately
    )
    response = _get_agent().invoke([system_message()] + history)
    return {"messages": [response]}
