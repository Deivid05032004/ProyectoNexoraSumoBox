from datetime import datetime, timedelta, timezone

import bcrypt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import jwt

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY

_PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1,
                                 hash_len=32, salt_len=16, type=Type.ID)


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > 1024:
        raise ValueError("La contraseña supera el máximo de 1024 bytes.")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > 1024:
        return False
    try:
        if password_hash.startswith("$argon2id$"):
            return _PASSWORD_HASHER.verify(password_hash, password)
        if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            return bcrypt.checkpw(encoded[:72], password_hash.encode("ascii"))
        return False
    except (ValueError, TypeError, InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_hash_needs_upgrade(password_hash: str) -> bool:
    if not password_hash.startswith("$argon2id$"):
        return True
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return True


def create_access_token(user_id: int, role: str, token_version: int = 0) -> str:
    if len(SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY no está configurada correctamente.")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "role": role, "ver": token_version, "iat": now,
         "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
