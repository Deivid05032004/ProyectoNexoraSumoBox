from pydantic import BaseModel, ConfigDict, Field


class RegistrationParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participant_id: int = Field(gt=0)
    role: str = Field(pattern="^(PARTICIPANT|COACH)$")


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: int = Field(gt=0)
    category_id: int = Field(gt=0)
    team_id: int = Field(gt=0)
    robot_id: int = Field(gt=0)
    participants: list[RegistrationParticipant] = Field(min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)


class RegistrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=1000)


class RegistrationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(APPROVED|OBSERVED|REJECTED|PENDING)$")
    comments: str | None = Field(default=None, max_length=1000)
