"""Generates the Tasman working data:

1. One ficha técnica (Excel) per hotel in src/data/hotels/ — editable by hand.
2. The Cloudbeds mock database (output/cloudbeds_pms.xlsx) seeded with
   reservations so each hotel shows a different occupancy profile.
3. Empty LEADS files (one per hotel + LEADS GRUPOS TASMAN) and CRM TASMAN.

Run:  python -m src.data.generate_tasman_data
"""

import random
from datetime import date, timedelta

import pandas as pd

from src.config.settings import (CRM_FILE, GROUP_LEADS_FILE, HOTELS,
                                 HOTELS_DIR, LEADS_DIR, PMS_FILE, QUOTES_DIR,
                                 hotel_data_file, hotel_leads_file)

# ---------------------------------------------------------------- fichas

FICHAS = {
    "AMINA": {
        "info": {
            "name": "Amina Wind Resort",
            "destino": "Punta de Mita, Nayarit",
            "categoria": "Resort de playa · 5 estrellas",
            "address": "Carretera Punta de Mita Km 11.5, Nayarit, México",
            "phone": "+52 329 291 6000",
            "email": "reservas@aminawind.mx",
            "check_in_time": "15:00",
            "check_out_time": "12:00",
            "descripcion": "Resort frente al mar con playa privada, tres piscinas, "
                           "beach club y deportes de viento (kitesurf, vela).",
        },
        "rooms": [
            ("GDN", "Garden View", 2, "1 king o 2 queen", 4200, 30, "Vista jardín, balcón, minibar"),
            ("OCE", "Ocean View", 3, "1 king + sofá cama", 5800, 24, "Vista al mar, terraza, cafetera"),
            ("SWM", "Swim-Up Suite", 2, "1 king", 7400, 10, "Acceso directo a piscina, terraza privada"),
            ("VIL", "Villa Familiar", 6, "2 king + 2 individuales", 12500, 6, "2 recámaras, cocina, alberca privada"),
        ],
        "upsells": [
            ("PICKUP", "Pick-up aeropuerto PVR", 1800, "Traslado privado aeropuerto Puerto Vallarta"),
            ("KITE", "Clase de kitesurf", 2200, "2 horas con instructor certificado"),
            ("MARIETAS", "Tour Islas Marietas", 1650, "Lancha + snorkel + almuerzo"),
            ("CENA", "Cena romántica en playa", 3200, "Menú 4 tiempos frente al mar"),
        ],
        "event_spaces": [
            ("Salón Pacífico", 180, "Banquete, auditorio, escuela", 28000),
            ("Terraza Sunset", 120, "Cocktail, banquete", 22000),
            ("Playa privada", 250, "Ceremonia, banquete", 35000),
        ],
        "occ_target": 0.55,
    },
    "CALIZA": {
        "info": {
            "name": "Caliza Roma",
            "destino": "Roma Norte, Ciudad de México",
            "categoria": "Hotel boutique urbano · 4 estrellas",
            "address": "Calle Orizaba 87, Roma Norte, CDMX, México",
            "phone": "+52 55 5264 3300",
            "email": "reservas@calizaroma.mx",
            "check_in_time": "15:00",
            "check_out_time": "12:00",
            "descripcion": "Casona porfiriana restaurada en el corazón de la Roma: "
                           "rooftop bar, café de especialidad y galería de arte local.",
        },
        "rooms": [
            ("CLA", "Clásica", 2, "1 queen", 2800, 14, "Piso de duela, TV 50'', wifi fibra"),
            ("BAL", "Balcón Roma", 2, "1 king", 3600, 10, "Balcón a la calle Orizaba, tina"),
            ("ATE", "Atelier Suite", 3, "1 king + sofá cama", 4900, 6, "Sala, comedor, obra de artistas locales"),
        ],
        "upsells": [
            ("PICKUP", "Pick-up aeropuerto AICM", 950, "Traslado privado desde AICM"),
            ("TOURROMA", "Walking tour Roma-Condesa", 650, "3 horas, guía local, incluye café"),
            ("DESAY", "Desayuno de especialidad", 320, "Por persona, en Café Caliza"),
        ],
        "event_spaces": [
            ("Rooftop Caliza", 80, "Cocktail, cena", 18000),
            ("Galería", 50, "Auditorio, cocktail", 9500),
        ],
        "occ_target": 0.75,
    },
    "SAL": {
        "info": {
            "name": "Casa Sal",
            "destino": "Sayulita, Nayarit",
            "categoria": "Hotel de playa bohemio · 3 estrellas",
            "address": "Calle Delfines 12, Sayulita, Nayarit, México",
            "phone": "+52 329 291 3110",
            "email": "hola@casasal.mx",
            "check_in_time": "14:00",
            "check_out_time": "11:00",
            "descripcion": "Hotel surfero a dos cuadras de la playa de Sayulita: "
                           "alberca con palapa, renta de tablas y mezcalería propia.",
        },
        "rooms": [
            ("PAL", "Palapa", 2, "1 queen", 1900, 12, "Ventilador, hamaca, patio compartido"),
            ("SUR", "Surf Room", 3, "1 queen + litera", 2400, 8, "A/C, rack de tablas, terraza"),
            ("CAS", "Casita Sal", 4, "1 king + 2 individuales", 3800, 5, "Cocineta, sala exterior, A/C"),
        ],
        "upsells": [
            ("SURF", "Clase de surf", 850, "90 minutos, tabla incluida"),
            ("MEZCAL", "Cata de mezcal", 700, "5 etiquetas + botanas"),
            ("PICKUP", "Pick-up aeropuerto PVR", 1500, "Traslado compartido"),
        ],
        "event_spaces": [
            ("Jardín Palapa", 60, "Banquete, ceremonia", 8000),
        ],
        "occ_target": 0.35,
    },
    "TALAVERA": {
        "info": {
            "name": "Casa Talavera",
            "destino": "Centro Histórico, Puebla",
            "categoria": "Hotel boutique patrimonial · 4 estrellas",
            "address": "Av. 5 Oriente 208, Centro, Puebla, México",
            "phone": "+52 222 232 4040",
            "email": "reservas@casatalavera.mx",
            "check_in_time": "15:00",
            "check_out_time": "12:00",
            "descripcion": "Casona del s. XVII con patios de talavera original, "
                           "restaurante de cocina poblana y terraza con vista a la Catedral.",
        },
        "rooms": [
            ("TAL", "Talavera", 2, "1 queen", 2200, 12, "Techos altos, patio interior"),
            ("VIR", "Virreinal", 2, "1 king", 3100, 8, "Balcón al centro, tina de talavera"),
            ("MAE", "Suite Maestra", 4, "1 king + 2 individuales", 4600, 4, "Dos ambientes, comedor, vista Catedral"),
        ],
        "upsells": [
            ("TOURPUE", "Tour Puebla + Cholula", 1100, "Día completo con guía"),
            ("MOLE", "Taller de mole poblano", 900, "3 horas con chef, incluye comida"),
            ("PICKUP", "Pick-up aeropuerto PBC", 700, "Traslado privado"),
        ],
        "event_spaces": [
            ("Patio Central", 100, "Banquete, ceremonia", 15000),
            ("Salón Virreinal", 60, "Auditorio, banquete", 10000),
        ],
        "occ_target": 0.45,
    },
    "LAIVA": {
        "info": {
            "name": "Laiva",
            "destino": "Tulum, Quintana Roo",
            "categoria": "Eco-resort de selva y playa · 5 estrellas",
            "address": "Carretera Tulum-Boca Paila Km 7.5, Tulum, México",
            "phone": "+52 984 802 5500",
            "email": "reservas@laiva.mx",
            "check_in_time": "15:00",
            "check_out_time": "12:00",
            "descripcion": "Eco-resort entre selva y mar: cabañas de madera con "
                           "energía solar, cenote privado, temazcal y beach club.",
        },
        "rooms": [
            ("JUN", "Jungle Cabaña", 2, "1 king", 5200, 16, "Terraza en la selva, regadera exterior"),
            ("OCF", "Ocean Front", 2, "1 king", 7800, 12, "Frente al mar, plunge pool"),
            ("TRE", "Treehouse Suite", 3, "1 king + day bed", 9500, 6, "Elevada entre árboles, vista mar y selva"),
        ],
        "upsells": [
            ("CENOTE", "Cenote privado + temazcal", 2600, "Ceremonia de 2 horas"),
            ("TOURTUL", "Tour ruinas de Tulum + Sian Ka'an", 2100, "Día completo"),
            ("PICKUP", "Pick-up aeropuerto CUN", 2400, "Traslado privado desde Cancún"),
        ],
        "event_spaces": [
            ("Beach Club Laiva", 150, "Ceremonia, banquete", 40000),
            ("Palapa Selva", 90, "Banquete, retiro", 25000),
        ],
        "occ_target": 0.85,
    },
    "SANTA": {
        "info": {
            "name": "Santa Casa",
            "destino": "San Miguel de Allende, Guanajuato",
            "categoria": "Hotel boutique romántico · 4 estrellas",
            "address": "Callejón de los Suspiros 5, Centro, San Miguel de Allende, México",
            "phone": "+52 415 152 7788",
            "email": "reservas@santacasa.mx",
            "check_in_time": "15:00",
            "check_out_time": "12:00",
            "descripcion": "Casona colonial a tres cuadras de la Parroquia: rooftop "
                           "con vista a las cúpulas, cava de vinos de Guanajuato y spa íntimo.",
        },
        "rooms": [
            ("COL", "Colonial", 2, "1 queen", 2600, 10, "Chimenea, patio con fuente"),
            ("CUP", "Vista Cúpulas", 2, "1 king", 3800, 7, "Terraza privada con vista a la Parroquia"),
            ("NUP", "Suite Nupcial", 2, "1 king", 5400, 3, "Tina doble, terraza, cava incluida"),
        ],
        "upsells": [
            ("VINO", "Cata de vinos de Guanajuato", 950, "6 etiquetas con sommelier"),
            ("GLOBO", "Vuelo en globo al amanecer", 3900, "Incluye brindis y desayuno"),
            ("PICKUP", "Pick-up aeropuerto BJX", 1300, "Traslado privado desde León"),
        ],
        "event_spaces": [
            ("Rooftop Cúpulas", 70, "Ceremonia, cocktail", 16000),
            ("Patio de la Fuente", 90, "Banquete, ceremonia", 14000),
        ],
        "occ_target": 0.25,
    },
}

# Políticas compartidas del grupo (editables por hotel en su ficha)
POLICIES = [
    ("Cancelación", "Gratuita hasta 72 h antes del check-in. Después se cobra la primera noche."),
    ("Niños", "Menores de 6 años no pagan compartiendo cama."),
    ("Pago", "Individual: link de pago para garantizar. Grupos: 50% de anticipo, saldo 15 días antes."),
    ("Mascotas", "Consultar por hotel; cargo de $800 MXN por estadía donde aplica."),
    ("Impuestos", "Tarifas más 16% de IVA. ISH incluido en la tarifa."),
    ("Fumadores", "Hoteles 100% libres de humo. Zonas designadas en exteriores."),
]


def _write_ficha(code: str) -> None:
    ficha = FICHAS[code]
    path = hotel_data_file(code)
    info = pd.DataFrame(list(ficha["info"].items()), columns=["key", "value"])
    rooms = pd.DataFrame(ficha["rooms"], columns=[
        "room_type_id", "name", "capacity", "beds",
        "base_rate_mxn", "quantity", "amenities"])
    policies = pd.DataFrame(POLICIES, columns=["policy", "detail"])
    upsells = pd.DataFrame(ficha["upsells"], columns=[
        "upsell_id", "name", "price_mxn", "description"])
    spaces = pd.DataFrame(ficha["event_spaces"], columns=[
        "space", "capacity", "setups", "rent_mxn"])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        info.to_excel(writer, sheet_name="hotel_info", index=False)
        rooms.to_excel(writer, sheet_name="rooms", index=False)
        policies.to_excel(writer, sheet_name="policies", index=False)
        upsells.to_excel(writer, sheet_name="upsells", index=False)
        spaces.to_excel(writer, sheet_name="event_spaces", index=False)


# ------------------------------------------------------- Cloudbeds seed

def _seed_pms() -> None:
    """Seeds the mock PMS with reservations so each hotel has a distinct
    occupancy profile (deterministic: fixed RNG seed)."""
    rng = random.Random(42)
    horizon = 120
    today = date.today()
    rows = []
    counter = 1
    for code, ficha in FICHAS.items():
        room_ids = [r[0] for r in ficha["rooms"]]
        quantities = {r[0]: r[5] for r in ficha["rooms"]}
        total_rooms = sum(quantities.values())
        target_nights = int(total_rooms * horizon * ficha["occ_target"])
        booked = 0
        while booked < target_nights:
            room_type = rng.choice(room_ids)
            start = today + timedelta(days=rng.randint(0, horizon - 1))
            nights = rng.randint(1, 4)
            rooms_count = rng.randint(1, min(3, quantities[room_type]))
            rows.append({
                "reservation_id": f"CB-{code}-S{counter:05d}",
                "hotel_code": code,
                "room_type_id": room_type,
                "rooms": rooms_count,
                "guest_name": "Seed booking",
                "check_in": start.isoformat(),
                "check_out": (start + timedelta(days=nights)).isoformat(),
                "status": "confirmed",
                "source": "seed",
                "notes": "",
            })
            booked += nights * rooms_count
            counter += 1
    pd.DataFrame(rows).to_excel(PMS_FILE, sheet_name="reservations", index=False)


# ------------------------------------------------- empty working files

INDIVIDUAL_LEAD_COLUMNS = [
    "lead_id", "created_at", "canal", "hotel", "guest_name", "guest_contact",
    "motivo", "personas", "habitaciones", "room_type_id", "check_in",
    "check_out", "total_mxn", "status", "next_followup", "followups_sent",
    "last_update", "cloudbeds_id", "notas",
]

GROUP_LEAD_COLUMNS = [
    "lead_id", "created_at", "canal", "hotel", "contacto", "empresa", "correo",
    "tipo_evento", "habitaciones", "personas", "check_in", "check_out",
    "servicios", "occ_pct", "descuento_pct", "total_mxn", "status",
    "aprobado_por", "last_update", "cloudbeds_id", "notas",
]

CRM_B2B_COLUMNS = ["empresa", "contacto", "correo", "hotel_interes",
                   "origen", "created_at", "last_interaction", "notas"]
CRM_B2C_COLUMNS = ["nombre", "contacto", "hotel_interes", "motivo",
                   "origen", "created_at", "last_interaction", "notas"]


def _create_working_files() -> None:
    for code in HOTELS:
        path = hotel_leads_file(code)
        if not path.exists():
            pd.DataFrame(columns=INDIVIDUAL_LEAD_COLUMNS).to_excel(
                path, sheet_name="Individuales", index=False)
    if not GROUP_LEADS_FILE.exists():
        pd.DataFrame(columns=GROUP_LEAD_COLUMNS).to_excel(
            GROUP_LEADS_FILE, sheet_name="Grupos", index=False)
    if not CRM_FILE.exists():
        with pd.ExcelWriter(CRM_FILE, engine="openpyxl") as writer:
            pd.DataFrame(columns=CRM_B2B_COLUMNS).to_excel(writer, sheet_name="B2B", index=False)
            pd.DataFrame(columns=CRM_B2C_COLUMNS).to_excel(writer, sheet_name="B2C", index=False)


def main() -> None:
    for directory in (HOTELS_DIR, LEADS_DIR, QUOTES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    for code in FICHAS:
        _write_ficha(code)
        print(f"Ficha técnica generada: {hotel_data_file(code).name}")
    _seed_pms()
    print(f"Cloudbeds mock sembrado: {PMS_FILE.name}")
    _create_working_files()
    print("Archivos de trabajo listos: LEADS por hotel, LEADS GRUPOS TASMAN, CRM TASMAN")


if __name__ == "__main__":
    main()
