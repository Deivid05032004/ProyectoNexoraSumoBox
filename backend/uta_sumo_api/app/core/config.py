from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    secret_key: str = ""
    pii_encryption_key: str = ""
    google_client_id: str = ""
    email_check_deliverability: bool = True
    access_token_expire_minutes: int = 30
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    receipt_storage_dir: str | None = None
    max_receipt_bytes: int = 5 * 1024 * 1024


settings = Settings()
SECRET_KEY = settings.secret_key
PII_ENCRYPTION_KEY = settings.pii_encryption_key
if not PII_ENCRYPTION_KEY:
    raise RuntimeError("PII_ENCRYPTION_KEY debe configurarse antes de iniciar la API.")
EMAIL_CHECK_DELIVERABILITY = settings.email_check_deliverability
GOOGLE_CLIENT_ID = settings.google_client_id.strip()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
ALLOWED_ORIGINS = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if "*" in ALLOWED_ORIGINS:
    raise RuntimeError("CORS_ORIGINS no admite '*' cuando se permiten credenciales.")
RECEIPT_STORAGE_DIR = Path(settings.receipt_storage_dir or (BASE_DIR / "storage" / "receipts")).resolve()
MAX_RECEIPT_BYTES = settings.max_receipt_bytes
if ACCESS_TOKEN_EXPIRE_MINUTES < 1 or ACCESS_TOKEN_EXPIRE_MINUTES > 1440:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES debe estar entre 1 y 1440.")
if MAX_RECEIPT_BYTES < 1024 or MAX_RECEIPT_BYTES > 20 * 1024 * 1024:
    raise RuntimeError("MAX_RECEIPT_BYTES debe estar entre 1 KiB y 20 MiB.")
