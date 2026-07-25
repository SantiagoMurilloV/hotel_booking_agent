"""Sends the pending automatic follow-ups (cadencia 1/3/5 días del SLA).
In production a scheduler (cron) runs this daily; in the console phase it
runs on demand.

Run:  python -m src.jobs.run_followups
"""

from src.services.followup_service import run_pending


def main() -> None:
    sent = run_pending()
    if not sent:
        print("Sin seguimientos pendientes para hoy.")
    else:
        print(f"{len(sent)} seguimiento(s) enviados y reprogramados.")


if __name__ == "__main__":
    main()
