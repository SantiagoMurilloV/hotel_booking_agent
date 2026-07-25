"""Automated reports to Slack (simulated in console during this phase).

Run:  python -m src.jobs.run_reports [kpis|directivo|operativo|todos]

- kpis:      lunes y jueves — KPIs y blockers → Slack Ventas HQ
- directivo: semanal — high level para la reunión directiva
- operativo: semanal — por cada hotel, a su canal operativo
"""

import sys

from src.services import reporting_service


def main() -> None:
    which = (sys.argv[1] if len(sys.argv) > 1 else "todos").lower()
    if which in ("kpis", "todos"):
        reporting_service.publish_kpis()
    if which in ("directivo", "todos"):
        reporting_service.publish_executive()
    if which in ("operativo", "todos"):
        reporting_service.publish_operational()
    if which not in ("kpis", "directivo", "operativo", "todos"):
        print("Uso: python -m src.jobs.run_reports [kpis|directivo|operativo|todos]")


if __name__ == "__main__":
    main()
