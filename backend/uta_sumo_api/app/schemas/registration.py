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
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_roster(self):
        # Compatibilidad temporal con el formulario desplegado, que envía el
        # perfil autenticado explícitamente. Las inscripciones completas usan
        # el orden PARTICIPANT, PARTICIPANT, COACH.
        if (len(self.participants) == 1
                and self.participants[0].participant_id is not None
                and self.participants[0].role == "PARTICIPANT"):
            return self

        if len(self.participants) != 3:
            raise ValueError("La inscripción requiere Participante 1, Participante 2 y Coach.")
        roles = [participant.role for participant in self.participants]
        if roles != ["PARTICIPANT", "PARTICIPANT", "COACH"]:
            raise ValueError("Ordene los integrantes como Participante 1, Participante 2 y Coach.")
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
