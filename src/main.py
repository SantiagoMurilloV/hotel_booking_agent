"""CLI entry point: interactive chat with the Tasman sales bot.

The same console plays two roles:
- the CLIENT chats normally;
- when a group quote needs internal validation, the console switches to
  [VALIDACIÓN ASESOR TASMAN] and a human approves/adjusts/rejects before
  the proposal reaches the client (flujo B).

Run:  python -m src.main
"""

import uuid

from langchain_core.messages import HumanMessage

from src.config.settings import HOTELS_DIR


def _ask_advisor(payload: dict) -> dict:
    print("\n" + "=" * 60)
    print("  🔒 VALIDACIÓN ASESOR TASMAN — cotización de grupo")
    print("=" * 60)
    for key in ("hotel", "contacto", "empresa", "tipo_evento",
                "habitaciones", "personas", "fechas", "room_type"):
        print(f"  {key.replace('_', ' ').capitalize():14}: {payload.get(key)}")
    print(f"  {'OCC del hotel':14}: {payload.get('occ_pct')}%")
    print(f"  {'Dto. por OCC':14}: {payload.get('descuento_pct')}%")
    if payload.get("nota_direccion"):
        print(f"  {payload['nota_direccion']}")
    print("  Cotización:")
    for concepto, valor in payload.get("cotizacion", {}).items():
        print(f"    - {concepto.replace('_', ' ')}: {valor}")
    print("-" * 60)
    print("  Opciones:  aprobar   ·   dto <n> (ajustar descuento %)   ·   rechazar <nota>")
    while True:
        raw = input("  [ASESOR] > ").strip()
        if not raw:
            continue
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if cmd in ("aprobar", "ok", "si", "sí"):
            return {"decision": "aprobar", "asesor": "Asesor Tasman (consola)"}
        if cmd == "dto":
            try:
                return {"decision": "ajustar", "descuento": float(rest),
                        "asesor": "Asesor Tasman (consola)",
                        "nota": f"Descuento ajustado a {rest}%"}
            except ValueError:
                print("  Uso: dto 12   (número de descuento %)")
                continue
        if cmd == "rechazar":
            return {"decision": "rechazar", "nota": rest or "sin nota",
                    "asesor": "Asesor Tasman (consola)"}
        print("  Comando no reconocido. Usa: aprobar · dto <n> · rechazar <nota>")


def main() -> None:
    if not HOTELS_DIR.exists() or not any(HOTELS_DIR.glob("*.xlsx")):
        print("Datos Tasman no encontrados. Generándolos primero...")
        from src.data.generate_tasman_data import main as generate_data
        generate_data()

    from langgraph.types import Command

    from src.orchestrator.graph import build_graph

    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("=" * 60)
    print("  TASMAN — Bot de ventas (6 hoteles) · consola")
    print("  (escribe 'salir' para terminar)")
    print("=" * 60)
    print("\n🛎️  ¡Hola! Soy el asistente de reservas de los hoteles TASMAN: "
          "Amina Wind Resort, Caliza Roma, Casa Sal, Casa Talavera, Laiva y "
          "Santa Casa. ¿En qué puedo ayudarte?\n")

    while True:
        try:
            user_input = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n¡Hasta pronto!")
            break
        if not user_input:
            continue
        if user_input.lower() in {"salir", "exit", "quit"}:
            print("¡Hasta pronto!")
            break

        result = graph.invoke({"messages": [HumanMessage(content=user_input)]}, config)
        while result.get("__interrupt__"):
            decision = _ask_advisor(result["__interrupt__"][0].value)
            result = graph.invoke(Command(resume=decision), config)
        print(f"\n🛎️  {result['messages'][-1].content}\n")


if __name__ == "__main__":
    main()
