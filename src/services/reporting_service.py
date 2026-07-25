"""Automated reports from the LEADS files (deterministic, zero tokens):
- KPIs y blockers (lunes y jueves) -> Slack Ventas HQ
- Reporte directivo semanal (pipeline 7/14/30 días)
- Reporte operativo por hotel (cotizaciones sin movimiento +1 semana)
"""

from datetime import date, timedelta

import pandas as pd

from src.config.settings import HOTELS
from src.services import leads_service, slack_service
from src.services.pricing_service import format_mxn


def _open_mask(df: pd.DataFrame) -> pd.Series:
    return ~df["status"].isin([leads_service.STATUS_WON, leads_service.STATUS_LOST])


def _hotel_kpis(code: str) -> dict:
    ind = leads_service.all_individual_leads()
    ind = ind[ind["hotel_code"] == code] if not ind.empty else ind
    grp = leads_service.all_group_leads()
    if not grp.empty:
        grp = grp[grp["hotel"] == HOTELS[code]]
    total = len(ind) + len(grp)
    won_ind = ind[ind["status"] == leads_service.STATUS_WON] if not ind.empty else pd.DataFrame()
    won_grp = grp[grp["status"] == leads_service.STATUS_WON] if not grp.empty else pd.DataFrame()
    won = len(won_ind) + len(won_grp)
    lost = ((ind["status"] == leads_service.STATUS_LOST).sum() if not ind.empty else 0) \
        + ((grp["status"] == leads_service.STATUS_LOST).sum() if not grp.empty else 0)
    revenue = (won_ind["total_mxn"].sum() if not won_ind.empty else 0) \
        + (won_grp["total_mxn"].sum() if not won_grp.empty else 0)
    open_leads = total - won - lost
    conversion = round(100 * won / total, 1) if total else 0.0
    return {"hotel": HOTELS[code], "leads": total, "won": won, "lost": int(lost),
            "open": int(open_leads), "conversion": conversion, "revenue": revenue}


def kpis_report() -> str:
    """Lunes y jueves — KPIs y blockers para Slack Ventas HQ."""
    lines = []
    for code in HOTELS:
        k = _hotel_kpis(code)
        lines.append(f"• {k['hotel']}: {k['leads']} leads · {k['open']} abiertos · "
                     f"{k['won']} won / {k['lost']} lost · conv. {k['conversion']}% · "
                     f"ventas {format_mxn(k['revenue'])}")
    stalled = _stalled_leads()
    lines.append("")
    if stalled:
        lines.append(f"🔴 Blockers: {len(stalled)} cotizaciones sin movimiento +7 días")
        for s in stalled[:10]:
            lines.append(f"   - {s['lead_id']} · {s['hotel']} · {s['status']} · "
                         f"último mov. {s['last_update']} → responsable: siguiente día hábil")
    else:
        lines.append("🟢 Sin blockers: ninguna cotización sin movimiento +7 días")
    return "\n".join(lines)


def _pipeline_window(days: int, today: date) -> tuple[int, float]:
    """Open leads with check-in inside the next N days: count and value."""
    limit = today + timedelta(days=days)
    count, value = 0, 0.0
    ind = leads_service.all_individual_leads()
    if not ind.empty:
        open_ind = ind[_open_mask(ind)]
        for _, row in open_ind.iterrows():
            ci = pd.to_datetime(row["check_in"]).date()
            if today <= ci <= limit:
                count += 1
                value += float(row["total_mxn"] or 0)
    grp = leads_service.all_group_leads()
    if not grp.empty:
        open_grp = grp[_open_mask(grp)]
        for _, row in open_grp.iterrows():
            ci = pd.to_datetime(row["check_in"]).date()
            if today <= ci <= limit:
                count += 1
                value += float(row["total_mxn"] or 0)
    return count, value


def executive_report(today: date | None = None) -> str:
    """Semanal — high level para la reunión directiva de ventas."""
    today = today or date.today()
    lines = []
    grp = leads_service.all_group_leads()
    if not grp.empty:
        big = grp[_open_mask(grp)].sort_values("total_mxn", ascending=False).head(5)
        if not big.empty:
            lines.append("Oportunidades grandes abiertas:")
            for _, row in big.iterrows():
                lines.append(f"• {row['lead_id']} · {row['hotel']} · {row['tipo_evento']} · "
                             f"{row['habitaciones']} hab · {format_mxn(row['total_mxn'])} · {row['status']}")
    for days in (7, 14, 30):
        count, value = _pipeline_window(days, today)
        lines.append(f"Pipeline {days}D: {count} oportunidades · {format_mxn(value)}")
    stalled = _stalled_leads()
    lines.append(f"Blockers activos: {len(stalled)} cotizaciones sin movimiento +7 días")
    return "\n".join(lines)


def _stalled_leads(days: int = 7) -> list[dict]:
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    stalled = []
    ind = leads_service.all_individual_leads()
    if not ind.empty:
        old = ind[_open_mask(ind) & (pd.to_datetime(ind["last_update"]) < cutoff)]
        stalled += old.to_dict(orient="records")
    grp = leads_service.all_group_leads()
    if not grp.empty:
        old = grp[_open_mask(grp) & (pd.to_datetime(grp["last_update"]) < cutoff)]
        stalled += old.to_dict(orient="records")
    return stalled


def hotel_operational_report(code: str) -> str:
    """Semanal — operativo por propiedad."""
    k = _hotel_kpis(code)
    lines = [f"Leads: {k['leads']} · abiertos {k['open']} · conv. {k['conversion']}% · "
             f"ventas {format_mxn(k['revenue'])}"]
    stalled = [s for s in _stalled_leads() if s.get("hotel") == HOTELS[code]]
    if stalled:
        lines.append(f"Cotizaciones sin movimiento +1 semana ({len(stalled)}):")
        for s in stalled:
            lines.append(f"• {s['lead_id']} · {s['status']} · último mov. {s['last_update']}")
    else:
        lines.append("Sin cotizaciones estancadas esta semana.")
    return "\n".join(lines)


def publish_kpis() -> None:
    slack_service.send_report(slack_service.CH_VENTAS_HQ,
                              "KPIs y blockers — Ventas Tasman", kpis_report())


def publish_executive() -> None:
    slack_service.send_report(slack_service.CH_DIRECCION,
                              "Reporte directivo semanal — Ventas", executive_report())


def publish_operational() -> None:
    for code in HOTELS:
        slack_service.send_report(slack_service.hotel_channel(code),
                                  f"Reporte operativo semanal — {HOTELS[code]}",
                                  hotel_operational_report(code))
