from pydantic import AliasChoices, BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator
from app.core.password_policy import validate_password


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: EmailStr = Field(validation_alias=AliasChoices("email", "username"), max_length=254)
    password: str = Field(min_length=15, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    institution_id: int = Field(gt=0)
    mobile_phone: str | None = Field(default=None, max_length=25)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().casefold()

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return validate_password(value)

    @model_validator(mode="after")
    def password_not_contain_email(self):
        validate_password(self.password, str(self.email))
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: EmailStr = Field(validation_alias=AliasChoices("email", "username"), max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().casefold()


class GoogleAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id_token: str = Field(min_length=100, max_length=8192)
    institution_id: int | None = Field(default=None, gt=0)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: EmailStr
    username: str  # compatibility alias; always contains the same email
    first_name: str
    last_name: str
    role: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return validate_password(value)
