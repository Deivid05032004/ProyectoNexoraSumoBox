from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class InstitutionInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)


class EventInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    edition_year: int = Field(ge=2000, le=2200)
    registration_start: date | None = None
    registration_end: date | None = None
    is_active: bool = True


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


class TeamInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    institution_id: int = Field(gt=0)
    contact_phone: str | None = Field(default=None, max_length=25)


class TeamUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    institution_id: int = Field(gt=0)
    contact_phone: str | None = Field(default=None, max_length=25)


class RobotInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    robot_description: str | None = Field(default=None, max_length=500)


class ParticipantUpdate(StrictModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    mobile_phone: str | None = Field(default=None, max_length=25)


class UserAdminUpdate(StrictModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(ADMIN|EVENT_MANAGER|PARTICIPANT)$")
