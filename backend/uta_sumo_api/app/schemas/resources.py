from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_category_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre de la categoría no puede quedar vacío.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_category_description(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None


class EventCategoryCreateInput(CategoryInput):
    is_active: bool = True
    min_participants: int = Field(default=1, ge=1, le=30)
    max_participants: int = Field(default=2, ge=1, le=30)
    min_coaches: int = Field(default=0, ge=0, le=30)
    max_coaches: int = Field(default=1, ge=0, le=30)
    max_registrations: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_participants > self.max_participants:
            raise ValueError("min_participants no puede superar max_participants.")
        if self.min_coaches > self.max_coaches:
            raise ValueError("min_coaches no puede superar max_coaches.")
        return self


class InstitutionInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)


class EventInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    edition_year: int = Field(ge=2000, le=2200)
    description: str | None = Field(default=None, max_length=2000)
    venue: str | None = Field(default=None, max_length=250)
    registration_start: date | None = None
    registration_end: date | None = None
    starts_at: str | None = Field(default=None, max_length=40)
    ends_at: str | None = Field(default=None, max_length=40)
    is_active: bool = True


class EventFormField(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=200)
    type: str = Field(pattern="^(short_text|long_text|email|number|date|single_choice|checkboxes|dropdown)$")
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)


class EventFormInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    fields: list[EventFormField] = Field(default_factory=list, max_length=50)


class EventStatusInput(StrictModel):
    status: str = Field(pattern="^(DRAFT|SCHEDULED|LIVE|PAUSED|FINISHED|CANCELLED)$")
    reason: str | None = Field(default=None, max_length=500)


class AdminUserCreate(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern="^(ADMIN|EVENT_MANAGER)$")
    password: str = Field(min_length=15, max_length=128)


class EventCategoryRulesInput(StrictModel):
    is_active: bool = True
    min_participants: int = Field(default=1, ge=1, le=30)
    max_participants: int = Field(default=30, ge=1, le=30)
    min_coaches: int = Field(default=0, ge=0, le=30)
    max_coaches: int = Field(default=30, ge=0, le=30)
    max_registrations: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_participants > self.max_participants:
            raise ValueError("min_participants no puede superar max_participants.")
        if self.min_coaches > self.max_coaches:
            raise ValueError("min_coaches no puede superar max_coaches.")
        return self


class TariffInput(StrictModel):
    event_id: int = Field(gt=0)
    category_id: int = Field(gt=0)
    amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    valid_from: date
    valid_until: date | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_validity(self):
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until no puede ser anterior a valid_from.")
        return self


class TeamInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    institution_id: int = Field(gt=0)
    contact_phone: str | None = Field(default=None, max_length=25)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del equipo no puede quedar vacío.")
        return value


class TeamUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    institution_id: int = Field(gt=0)
    contact_phone: str | None = Field(default=None, max_length=25)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del equipo no puede quedar vacío.")
        return value


class RobotInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    team_id: int | None = Field(default=None, gt=0)
    robot_description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del robot no puede quedar vacío.")
        return value


class RegistrationResourcesInput(StrictModel):
    team_name: str = Field(min_length=1, max_length=120)
    robot_name: str = Field(min_length=1, max_length=120)
    institution_id: int = Field(gt=0)
    contact_phone: str | None = Field(default=None, max_length=25)
    robot_description: str | None = Field(default=None, max_length=500)

    @field_validator("team_name", "robot_name")
    @classmethod
    def normalize_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede quedar vacío.")
        return value


class ParticipantUpdate(StrictModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    mobile_phone: str | None = Field(default=None, max_length=25)


class UserAdminUpdate(StrictModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(ADMIN|EVENT_MANAGER|PARTICIPANT)$")
