from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegistrationConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_name: str = Field(min_length=1, max_length=200)
    form_title: str = Field(min_length=1, max_length=200)
    form_description: str | None = Field(default=None, max_length=2000)
    form_instructions: str | None = Field(default=None, max_length=4000)
    payment_instructions: str | None = Field(default=None, max_length=6000)
    payment_methods: list[str] = Field(default_factory=list, max_length=10)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    receipt_message: str | None = Field(default=None, max_length=2000)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    is_enabled: bool = True

    @field_validator("organization_name", "form_title")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Este campo no puede estar vacío.")
        return value

    @field_validator("payment_methods")
    @classmethod
    def clean_methods(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 100 for value in cleaned):
            raise ValueError("Cada método de pago debe tener entre 1 y 100 caracteres.")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("No repita métodos de pago.")
        return cleaned
