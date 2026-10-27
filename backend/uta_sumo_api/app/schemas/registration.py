from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegistrationParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_id: int | None = Field(default=None, gt=0)
    role: str = Field(pattern="^(PARTICIPANT|COACH)$")
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    institution_id: int | None = Field(default=None, gt=0)
    mobile_phone: str | None = Field(default=None, max_length=25)

    @field_validator("first_name", "last_name")
    @classmethod
    def trim_names(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede quedar vacío.")
        return value

    @field_validator("mobile_phone")
    @classmethod
    def trim_mobile_phone(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_identity_source(self):
        details = (self.first_name, self.last_name, self.institution_id, self.mobile_phone)
        if self.participant_id is not None:
            if any(value is not None for value in details):
                raise ValueError("Use participant_id o los datos personales, no ambos.")
            return self

        if not self.first_name or not self.last_name or self.institution_id is None:
            raise ValueError("Cada integrante nuevo requiere nombres, apellidos e institución.")
        if "mobile_phone" not in self.model_fields_set:
            raise ValueError("Incluya mobile_phone; use null si no tiene celular.")
        return self


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: int = Field(gt=0)
    category_id: int = Field(gt=0)
    team_id: int = Field(gt=0)
    robot_id: int = Field(gt=0)
    participants: list[RegistrationParticipant] = Field(min_length=1, max_length=30)
    custom_answers: dict[str, Any] = Field(default_factory=dict, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_roster(self):
        # La cardinalidad/mezcla permitida se configura por evento y categoría
        # en SQL; aquí se validan solo invariantes independientes del evento.
        if not any(person.role == "PARTICIPANT" for person in self.participants):
            raise ValueError("La inscripción requiere al menos un integrante PARTICIPANT.")
        # Stop unreasonable payloads before querying category-specific limits;
        # the exact min/max remains configurable per event in SQL.
        if sum(person.role == "PARTICIPANT" for person in self.participants) > 30:
            raise ValueError("Una inscripción no puede superar 30 participantes.")
        if sum(person.role == "COACH" for person in self.participants) > 30:
            raise ValueError("Una inscripción no puede superar 30 coaches.")
        inline_people = [
            (p.first_name.casefold(), p.last_name.casefold(), p.institution_id,
             (p.mobile_phone or "").casefold())
            for p in self.participants if p.participant_id is None
        ]
        if len(inline_people) != len(set(inline_people)):
            raise ValueError("No repita los mismos datos personales en el roster.")
        return self


class RegistrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=1000)


class RegistrationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(APPROVED|OBSERVED|REJECTED|PENDING)$")
    comments: str | None = Field(default=None, max_length=1000)
