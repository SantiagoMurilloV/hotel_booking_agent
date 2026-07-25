"""Pydantic schemas shared across tools, nodes and services."""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from src.config.settings import HOTELS


class _DatedRequest(BaseModel):
    hotel_code: str = Field(description="Hotel code: AMINA, CALIZA, SAL, TALAVERA, LAIVA, SANTA")
    check_in: date
    check_out: date

    @field_validator("hotel_code")
    @classmethod
    def known_hotel(cls, v: str) -> str:
        code = v.strip().upper()
        if code not in HOTELS:
            raise ValueError(f"Unknown hotel code: {v}. Valid: {', '.join(HOTELS)}")
        return code

    @field_validator("check_out")
    @classmethod
    def checkout_after_checkin(cls, v: date, info) -> date:
        check_in = info.data.get("check_in")
        if check_in and v <= check_in:
            raise ValueError("check_out must be after check_in")
        return v


class ProposalRequest(_DatedRequest):
    """Individual proposal: 1-4 rooms."""
    guest_name: str = Field(description="Full name of the guest")
    guest_contact: str = Field(description="Email or phone of the guest")
    motivo: str = Field(default="", description="Reason of the trip (vacaciones, trabajo, festejo...)")
    room_type_id: str = Field(description="Room type code of the chosen hotel")
    habitaciones: int = Field(ge=1, le=4, description="Number of rooms (1-4)")
    personas: int = Field(ge=1)

    @field_validator("room_type_id")
    @classmethod
    def uppercase_room(cls, v: str) -> str:
        return v.strip().upper()


class GroupBrief(_DatedRequest):
    """Group with rooms: 5+ rooms or 15+ people."""
    contacto: str = Field(description="Full name of the contact person")
    correo: str = Field(description="Email or phone of the contact")
    empresa: str = Field(default="", description="Company or organization (empty if private group)")
    tipo_evento: str = Field(description="Type of event: boda, corporativo, retiro, congreso...")
    habitaciones: int = Field(ge=0)
    personas: int = Field(ge=1)
    servicios: str = Field(default="", description="Required services: salón, catering, AV, traslados...")


class EventBrief(BaseModel):
    """Event WITHOUT rooms (flujo D): venue, catering, AV..."""
    hotel_code: str
    contacto: str
    correo: str
    empresa: str = ""
    tipo_evento: str
    personas: int = Field(ge=1)
    fecha: date
    servicios: str = Field(description="Montaje, catering, señalización, audiovisual, traslados...")

    @field_validator("hotel_code")
    @classmethod
    def known_hotel(cls, v: str) -> str:
        code = v.strip().upper()
        if code not in HOTELS:
            raise ValueError(f"Unknown hotel code: {v}. Valid: {', '.join(HOTELS)}")
        return code


class Quote(BaseModel):
    nights: int
    rooms: int
    room_subtotal: float
    discount_pct: float = 0.0
    discount_amount: float = 0.0
    taxes: float
    total: float
    currency: str = "MXN"
    nightly_rate: float = 0.0
