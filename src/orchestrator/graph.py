"""LangGraph wiring of the Tasman sales bot.

chat ↔ tools loop; three intercepted tools branch into deterministic
pipelines: create_reservation (individual, parallel fan-out),
submit_group_brief (group quote + human validation) and
create_group_reservation (group Closed Won).
"""

from typing import Annotated, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.nodes.action_nodes import notify_node, records_node
from src.nodes.chat_node import chat_node
from src.nodes.confirmation_node import confirmation_node
from src.nodes.group_nodes import group_pipeline_node, group_won_node
from src.nodes.summary_node import summary_node
from src.tools.tasman_tools import CHAT_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    reservation: Optional[dict]
    notify_result: Optional[str]
    records_result: Optional[str]


def route_after_chat(state: AgentState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return END
    names = {tc["name"] for tc in tool_calls}
    if "create_reservation" in names:
        return "confirm"
    if "submit_group_brief" in names:
        return "group"
    if "create_group_reservation" in names:
        return "group_won"
    return "tools"


def route_after_confirm(state: AgentState) -> list[str] | str:
    if state.get("reservation"):
        return ["notify", "records"]  # parallel fan-out
    return "chat"  # validation failed: let the agent explain and recover


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("chat", chat_node)
    graph.add_node("tools", ToolNode(CHAT_TOOLS))
    graph.add_node("confirm", confirmation_node)
    graph.add_node("group", group_pipeline_node)
    graph.add_node("group_won", group_won_node)
    graph.add_node("notify", notify_node)
    graph.add_node("records", records_node)
    graph.add_node("summary", summary_node)

    graph.add_edge(START, "chat")
    graph.add_conditional_edges("chat", route_after_chat,
                                {END: END, "confirm": "confirm", "group": "group",
                                 "group_won": "group_won", "tools": "tools"})
    graph.add_edge("tools", "chat")
    graph.add_conditional_edges("confirm", route_after_confirm,
                                ["chat", "notify", "records"])
    graph.add_edge("group", "chat")
    graph.add_edge("group_won", END)
    graph.add_edge("notify", "summary")
    graph.add_edge("records", "summary")
    graph.add_edge("summary", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
