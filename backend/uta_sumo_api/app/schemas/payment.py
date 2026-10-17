from pydantic import BaseModel, ConfigDict, Field


class PaymentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(PAID|REJECTED)$")
    comments: str | None = Field(default=None, max_length=1000)
