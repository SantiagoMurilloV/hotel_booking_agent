"""Deterministic smoke test of the Tasman pipeline — no API key needed.

Covers: data generation, fichas, Cloudbeds mock (availability, OCC,
reservations), OCC->discount table, MXN quotes with IVA 16%, individual
lead registration + follow-up cadence, group lead registration, CRM,
PDF generation and reports.

Run:  python -m tests.smoke_test
"""

from datetime import date, timedelta

from src.config.settings import HOTELS
from src.services import (cloudbeds_service, crm_service, hotel_data_service,
                          leads_service, pdf_service)
from src.services.followup_service import cadence_days
from src.services.pricing_service import build_quote, discount_for_occ, format_mxn
from src.services.reporting_service import (executive_report,
                                            hotel_operational_report,
                                            kpis_report)


def main() -> None:
    from src.data.generate_tasman_data import main as generate
    generate()

    # Fichas técnicas: 6 hoteles completos
    assert len(hotel_data_service.hotel_directory()) == 6
    for code in HOTELS:
        assert hotel_data_service.get_rooms(code), f"{code} sin habitaciones"
        assert hotel_data_service.get_upsells(code), f"{code} sin upsells"
    print("✅ Fichas técnicas de los 6 hoteles")

    # Cloudbeds mock: disponibilidad y OCC
    ci, co = date.today() + timedelta(days=30), date.today() + timedelta(days=33)
    avail = cloudbeds_service.availability_by_room("SAL", ci, co)
    assert any(r["available_units"] > 0 for r in avail)
    occ_low = cloudbeds_service.get_occupancy("SANTA", ci, co)
    occ_high = cloudbeds_service.get_occupancy("LAIVA", ci, co)
    assert occ_low < occ_high, "los perfiles de ocupación deben diferir"
    print(f"✅ Cloudbeds mock: OCC SANTA {occ_low}% < OCC LAIVA {occ_high}%")

    # Tabla de descuentos OCC
    assert discount_for_occ(30) == 20
    assert discount_for_occ(60) == 15
    assert discount_for_occ(85) == 10
    assert discount_for_occ(95) == 0
    print("✅ Tabla OCC → descuento")

    # Cotización MXN con IVA 16%
    quote = build_quote("CALIZA", "CLA", ci, co, rooms=2)
    assert quote.nights == 3 and quote.rooms == 2
    assert quote.room_subtotal == 2800 * 3 * 2
    assert quote.taxes == round(quote.room_subtotal * 0.16)
    gq = build_quote("CALIZA", "CLA", ci, co, rooms=6, discount_pct=15)
    assert gq.discount_amount == round(2800 * 3 * 6 * 0.15)
    print(f"✅ Cotizaciones MXN: individual {format_mxn(quote.total)}, "
          f"grupo c/dto {format_mxn(gq.total)}")

    # Lead individual + cadencia de seguimiento
    lead_id = leads_service.register_individual_lead(
        "CALIZA", guest_name="Prueba Humo", guest_contact="humo@test.mx",
        motivo="test", personas=2, habitaciones=1, room_type_id="CLA",
        check_in=ci.isoformat(), check_out=co.isoformat(),
        total_mxn=quote.total, next_followup=date.today().isoformat())
    lead = leads_service.get_individual_lead(lead_id)
    assert lead["status"] == leads_service.STATUS_PROPUESTA
    assert cadence_days(date.today() + timedelta(days=3)) == 1
    assert cadence_days(date.today() + timedelta(days=10)) == 3
    assert cadence_days(date.today() + timedelta(days=30)) == 5
    assert len(leads_service.due_followups()) >= 1
    print(f"✅ Lead individual {lead_id} + cadencia 1/3/5")

    # Reserva en Cloudbeds y Closed Won
    cb_id = cloudbeds_service.create_reservation(
        "CALIZA", "CLA", 1, "Prueba Humo", ci, co)
    assert cloudbeds_service.append_reservation_note(cb_id, "Requerimientos: cuna")
    leads_service.update_individual_lead(lead_id,
                                         status=leads_service.STATUS_WON,
                                         cloudbeds_id=cb_id, next_followup="")
    assert leads_service.get_individual_lead(lead_id)["status"] == leads_service.STATUS_WON
    print(f"✅ Reserva Cloudbeds {cb_id} → Closed Won")

    # Lead de grupo + CRM B2B
    gr_id = leads_service.register_group_lead(
        "AMINA", contacto="Coordinadora Evento", empresa="ACME SA",
        correo="eventos@acme.mx", tipo_evento="corporativo", habitaciones=10,
        personas=20, check_in=ci.isoformat(), check_out=co.isoformat(),
        servicios="salón, AV", occ_pct=45.0, descuento_pct=20.0,
        total_mxn=gq.total, status=leads_service.STATUS_PROPUESTA,
        aprobado_por="Asesor Test", notas="room_type=GDN")
    assert leads_service.get_group_lead(gr_id)["hotel_code"] == "AMINA"
    crm_service.upsert_b2b("ACME SA", "Coordinadora Evento", "eventos@acme.mx", "AMINA")
    crm_service.upsert_b2c("Prueba Humo", "humo@test.mx", "CALIZA", motivo="test")
    print(f"✅ Lead grupo {gr_id} + CRM B2B/B2C")

    # PDF de cotización
    pdf = pdf_service.generate_quote_pdf({
        "hotel_code": "CALIZA", "reference": lead_id,
        "guest_name": "Prueba Humo", "guest_contact": "humo@test.mx",
        "room_name": "Clásica", "habitaciones": 1, "personas": 2,
        "check_in": ci.isoformat(), "check_out": co.isoformat(),
        "quote": quote.model_dump(),
        "payment_link": cloudbeds_service.payment_link(lead_id)})
    print(f"✅ PDF generado: {pdf}")

    # Reportes
    assert "leads" in kpis_report().lower()
    assert "Pipeline 7D" in executive_report()
    assert hotel_operational_report("CALIZA")
    print("✅ Reportes KPIs / directivo / operativo")

    print("\n🎉 Smoke test Tasman completo: todo el pipeline determinista funciona.")


if __name__ == "__main__":
    main()
