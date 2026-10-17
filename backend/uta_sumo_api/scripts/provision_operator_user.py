"""Interactively provision a privileged operator; never contains defaults/secrets."""
from getpass import getpass
from email_validator import EmailNotValidError, validate_email

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.core.crypto import email_lookup_hash, encrypt_text
from app.core.password_policy import validate_password
from database import SessionLocal


def main() -> None:
    email = input("Correo electrónico: ").strip()
    first_name = input("Nombre: ").strip()
    last_name = input("Apellido: ").strip()
    role = input("Rol (ADMIN/REVIEWER/TREASURY): ").strip().upper()
    if role not in {"ADMIN", "REVIEWER", "TREASURY"}:
        raise SystemExit("Rol no permitido por este aprovisionador.")
    password = getpass("Contraseña inicial (15 caracteres mínimo): ")
    confirm = getpass("Confirma la contraseña: ")
    try:
        email = validate_email(email, check_deliverability=True, timeout=5,
                               globally_deliverable=True).normalized.casefold()
    except EmailNotValidError as exc:
        raise SystemExit("El correo o su dominio no es válido.") from exc
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not first_name or not last_name or len(first_name) > 100 or len(last_name) > 100:
        raise SystemExit("Nombre y apellido son obligatorios y no deben superar 100 caracteres.")
    if len(email) > 254:
        raise SystemExit("El correo supera el máximo de 254 caracteres.")
    if password != confirm:
        raise SystemExit("Las contraseñas no coinciden.")
    try:
        validate_password(password, email)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    db = SessionLocal()
    try:
        role_id = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:role"),
                             {"role": role}).scalar_one_or_none()
        if role_id is None:
            raise SystemExit(f"El rol {role} no existe. Revise los datos iniciales de SQL.")
        user_id = db.execute(text("""
            INSERT INTO dbo.Users (EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive)
            OUTPUT INSERTED.UserId
            VALUES (:email,:lookup,:password_hash,:first,:last,:role_id,1)
        """), {"email": encrypt_text(email), "lookup": email_lookup_hash(email),
              "password_hash": hash_password(password), "first": encrypt_text(first_name),
              "last": encrypt_text(last_name), "role_id": role_id}).scalar_one()
        db.execute(text("INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode,NewRoleId,NewIsActive) VALUES (:id,:id,'ACCOUNT_CREATED',:role,1)"), {"id": user_id, "role": role_id})
        db.commit()
        print(f"Creado UserId={user_id}, email={email}, role={role}. La contraseña no se muestra ni se almacena en texto plano.")
    except IntegrityError:
        db.rollback()
        raise SystemExit("El correo ya existe; no se realizaron cambios.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
