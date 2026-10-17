"""Shared password rules for participant registration and operator provisioning."""

COMMON_PASSWORDS = {
    "123456789012345", "passwordpassword", "qwertyuiopasdfg",
    "letmeinletmein1", "administrator", "welcome12345678",
}


def validate_password(password: str, email: str | None = None) -> str:
    if len(password) < 15:
        raise ValueError("Use una frase de contraseña de al menos 15 caracteres.")
    if len(password) > 128 or len(password.encode("utf-8")) > 1024:
        raise ValueError("La contraseña supera el máximo permitido.")
    folded = password.casefold()
    if folded in COMMON_PASSWORDS or folded in {"a" * 15, "1" * 15, "0" * 15}:
        raise ValueError("Esa contraseña es demasiado común o predecible.")
    if any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise ValueError("La contraseña no puede contener caracteres de control.")
    if email:
        local = email.split("@", 1)[0].casefold()
        if len(local) >= 4 and local in folded:
            raise ValueError("La contraseña no debe contener el correo.")
    return password
