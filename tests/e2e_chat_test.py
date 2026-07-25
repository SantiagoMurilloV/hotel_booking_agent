"""End-to-end conversational test against the real LLM.

Two scripted conversations:
1. INDIVIDUAL: quote -> proposal -> confirmation (Closed Won in Cloudbeds).
2. GRUPO: brief -> OCC quote -> advisor approval (auto-resumed) -> proposal.

Run:  python -m tests.e2e_chat_test   (requires DEEPSEEK_API_KEY)
"""

import uuid
from datetime import date, timedelta

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.orchestrator.graph import build_graph

CI = (date.today() + timedelta(days=40)).isoformat()
CO = (date.today() + timedelta(days=42)).isoformat()

INDIVIDUAL_SCRIPT = [
    f"Hola! ¿Qué habitaciones tiene Casa Sal del {CI} al {CO} para 2 personas?",
    "Me gusta la más económica. Cotízamela por favor: soy Ana Pérez, "
    "correo ana.perez@test.mx, 2 personas, 1 habitación, vamos de vacaciones.",
    "¡Perfecto, la acepto! Confirma la reserva por favor.",
]

GROUP_SCRIPT = [
    f"Hola, organizo un retiro corporativo: necesitamos 8 habitaciones en Santa Casa "
    f"del {CI} al {CO}, somos 16 personas. Soy Luis Ramos de Grupo Andino, "
    "correo luis@andino.mx. Necesitamos salón y coffee break.",
    "Habitaciones Coloniales están bien, el Patio de la Fuente como salón y solo "
    "coffee break. Genera la cotización por favor.",
]


def run_script(graph, script, auto_approve=False):
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = None
    for turn in script:
        print(f"\n{'=' * 70}\nCLIENTE: {turn}\n")
        result = graph.invoke({"messages": [HumanMessage(content=turn)]}, config)
        while result.get("__interrupt__"):
            assert auto_approve, "Unexpected interrupt in individual flow"
            payload = result["__interrupt__"][0].value
            print(f"[ASESOR AUTO] aprueba cotización: OCC {payload['occ_pct']}% "
                  f"→ dto {payload['descuento_pct']}%")
            result = graph.invoke(
                Command(resume={"decision": "aprobar", "asesor": "Asesor E2E"}), config)
        print(f"BOT: {result['messages'][-1].content}")
    return result


def main() -> None:
    graph = build_graph()

    print("\n########## FLUJO A · INDIVIDUAL ##########")
    result = run_script(graph, INDIVIDUAL_SCRIPT)
    final = result["messages"][-1].content
    assert "CB-SAL-" in final, "Expected a Cloudbeds id in the final message"
    print("\n✔ Flujo A: reserva individual confirmada de punta a punta.")

    print("\n########## FLUJO B · GRUPO ##########")
    result = run_script(graph, GROUP_SCRIPT, auto_approve=True)
    from src.services import leads_service
    groups = leads_service.all_group_leads()
    assert not groups.empty and (groups["status"] == "PROPUESTA ENVIADA").any(), \
        "Expected a group lead registered as PROPUESTA ENVIADA"
    print("\n✔ Flujo B: brief → OCC → validación asesor → propuesta enviada y registrada.")

    print("\nE2E chat test passed ✔")


if __name__ == "__main__":
    main()
