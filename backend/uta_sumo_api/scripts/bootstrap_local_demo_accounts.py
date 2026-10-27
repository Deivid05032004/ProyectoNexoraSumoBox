"""Create disposable local demo identities with random passwords.

Credentials are printed once and never committed or stored in the database in
plaintext. This script refuses non-local/non-development database targets.
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from app.core.security import hash_password, verify_password
from app.core.crypto import email_lookup_hash, encrypt_text
from database import DB_NAME, DB_SERVER, SessionLocal

ACCOUNTS = (
    ("admin.demo@example.com", "ADMIN", "Demo", "Administrador"),
    ("event_manager.demo@example.com", "EVENT_MANAGER", "Demo", "Gestor de eventos"),
    ("administrator.demo@example.com", "ADMIN", "Demo", "Operador administrativo"),
    ("participant.demo@example.com", "PARTICIPANT", "Demo", "Participante"),
)
# Development-only convenience identity. This bootstrap is restricted to the
# local demo database. Its short, fixed password is intentionally unsuitable
# for a shared deployment and must be changed before any shared use.
DEFAULT_ADMIN = ("adminTics@uta.edu.ec", "ADMIN", "Admin", "UTA Tics")
DEFAULT_ADMIN_PASSWORD = "Admin@utaTics"
INSTITUTION = "UTA SUMO DEMO LOCAL"
EVENT = "UTA SUMO ROBOTICS CUP 2026"
CATEGORY = "MINI SUMO AMATEUR RC"
COLLECTION = API_DIR / "postman/UTA_Sumo_E2E.postman_collection.json"


def _local_server() -> bool:
    value = DB_SERVER.strip().lower()
    local = {".", "(local)", "localhost", "127.0.0.1", socket.gethostname().lower()}
    host = value.split(",", 1)[0].removeprefix("tcp:").strip()
    return host in local or host.split("\\", 1)[0] in local


def _run_postman(credentials, ids) -> int:
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise SystemExit("Newman no está instalado/disponible; cuentas creadas, pero no se ejecutó la colección.")
    values = {
        "baseUrl": "http://127.0.0.1:8000",
        **ids,
    }
    for username, role, password in credentials:
        prefix = role.lower()
        values[prefix + "Username"] = username
        values[prefix + "Password"] = password
    environment = {
        "id": "local-demo-generated",
        "name": "UTA Sumo demo privado (temporal)",
        "values": [
            {"key": key, "value": value, "enabled": True,
             **({"type": "secret"} if key.endswith("Password") else {})}
            for key, value in values.items()
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "Newman",
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json",
                                         prefix="uta-sumo-postman-", delete=False) as temp:
            json.dump(environment, temp, ensure_ascii=False)
            temp_path = Path(temp.name)
        command = [npx, "--yes", "newman", "run", str(COLLECTION),
                   "--environment", str(temp_path), "--reporters", "cli"]
        result = subprocess.run(command, cwd=API_DIR, check=False)
        return result.returncode
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-postman", action="store_true",
                        help="Ejecuta el flujo E2E de Newman usando un environment temporal borrado al salir.")
    parser.add_argument("--rotate-existing", action="store_true",
                        help="Rota las claves aleatorias de las cuentas demo existentes e invalida sus sesiones.")
    args = parser.parse_args()
    if DB_NAME != "UTA_SUMO_ROBOTICS_CUP" or not _local_server():
        raise SystemExit("Solo se permite crear perfiles demo en UTA_SUMO_ROBOTICS_CUP local.")

    db = SessionLocal()
    credentials: list[tuple[str, str, str]] = []
    try:
        account_specs = (*ACCOUNTS, DEFAULT_ADMIN)
        lookup_by_email = {email: email_lookup_hash(email) for email, *_ in account_specs}
        existing = db.execute(text("""
            SELECT u.UserId,u.EmailLookupHash,r.Code FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
            WHERE u.EmailLookupHash IN (:admin,:event_manager,:administrator,:participant,:default_admin)
        """), {"admin": lookup_by_email[ACCOUNTS[0][0]], "event_manager": lookup_by_email[ACCOUNTS[1][0]],
              "administrator": lookup_by_email[ACCOUNTS[2][0]], "participant": lookup_by_email[ACCOUNTS[3][0]],
              "default_admin": lookup_by_email[DEFAULT_ADMIN[0]]}).all()
        email_by_hash = {value: email for email, value in lookup_by_email.items()}
        expected = {email: role for email, role, *_ in account_specs}
        if any(expected.get(email_by_hash.get(lookup)) != role for _, lookup, role in existing):
            raise SystemExit("Un correo demo reservado ya existe con otro rol; no se modificó nada.")
        existing_users = {email_by_hash[lookup]: user_id for user_id, lookup, _ in existing}

        institution_id = db.execute(text("SELECT InstitutionId FROM dbo.Institutions WHERE Name=:name"),
                                    {"name": INSTITUTION}).scalar_one_or_none()
        if institution_id is None:
            institution_id = db.execute(text("""
                INSERT INTO dbo.Institutions(Name) OUTPUT INSERTED.InstitutionId VALUES (:name)
            """), {"name": INSTITUTION}).scalar_one()
        category_id = db.execute(text("SELECT CategoryId FROM dbo.Categories WHERE Name=:name"),
                                 {"name": CATEGORY}).scalar_one_or_none()
        if category_id is None:
            category_id = db.execute(text("""
                INSERT INTO dbo.Categories(Name,Description)
                OUTPUT INSERTED.CategoryId VALUES (:name,N'Categoría de demostración local.')
            """), {"name": CATEGORY}).scalar_one()
        event_id = db.execute(text("""
            SELECT EventId FROM dbo.Events WHERE Name=:name AND EditionYear=2026
        """), {"name": EVENT}).scalar_one_or_none()
        if event_id is None:
            raise SystemExit(
                "No existe el evento oficial UTA SUMO ROBOTICS CUP 2026. "
                "Ejecute primero todas las migraciones de database/scripts."
            )
        tariff_id = db.execute(text("""
            SELECT TOP (1) TariffId FROM dbo.Tariffs
            WHERE EventId=:event AND CategoryId=:category AND IsActive=1
            ORDER BY ValidFrom DESC,TariffId DESC
        """), {"event": event_id, "category": category_id}).scalar_one_or_none()
        if tariff_id is None:
            raise SystemExit(
                "El evento oficial no tiene tarifa activa para MINI SUMO AMATEUR RC. "
                "Revise las migraciones 21 a 23."
            )

        participant_id = db.execute(text("""
            SELECT ParticipantId FROM dbo.Participants p JOIN dbo.Users u ON u.UserId=p.UserId
            WHERE u.EmailLookupHash=:lookup
        """), {"lookup": lookup_by_email["participant.demo@example.com"]}).scalar_one_or_none()
        for username, role, first, last in ACCOUNTS:
            if username in existing_users and not args.rotate_existing:
                continue
            password = secrets.token_urlsafe(24)
            if username in existing_users:
                user_id = existing_users[username]
                db.execute(text("""
                    UPDATE dbo.Users SET PasswordHash=:password,TokenVersion=TokenVersion+1
                    WHERE UserId=:id
                """), {"password": hash_password(password), "id": user_id})
                db.execute(text("""
                    INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode)
                    VALUES (:target,:actor,'PASSWORD_CHANGED')
                """), {"target": user_id, "actor": user_id})
            else:
                role_id = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:role"),
                                     {"role": role}).scalar_one_or_none()
                if role_id is None:
                    raise SystemExit(f"Falta el rol {role}; ejecute primero las migraciones.")
                user_id = db.execute(text("""
                    INSERT INTO dbo.Users(EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive)
                    OUTPUT INSERTED.UserId
                    VALUES (:email,:lookup,:password,:first,:last,:role,1)
                """), {"email": encrypt_text(username), "lookup": lookup_by_email[username],
                      "password": hash_password(password), "first": encrypt_text(first),
                      "last": encrypt_text(f"{last} Local"), "role": role_id}).scalar_one()
                db.execute(text("""
                    INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActionCode,NewRoleId,NewIsActive)
                    VALUES (:target,'ACCOUNT_CREATED',:role,1)
                """), {"target": user_id, "role": role_id})
            if role == "PARTICIPANT" and participant_id is None:
                participant_id = db.execute(text("""
                    INSERT INTO dbo.Participants(FirstName,LastName,MobilePhone,InstitutionId,UserId)
                    OUTPUT INSERTED.ParticipantId
                    VALUES (:first,:last,NULL,:institution,:user)
                """), {"first": encrypt_text(first), "last": encrypt_text(last), "institution": institution_id,
                      "user": user_id}).scalar_one()
            credentials.append((username, role, password))
        default_admin_created = False
        if DEFAULT_ADMIN[0] not in existing_users:
            email, role, first, last = DEFAULT_ADMIN
            role_id = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:role"),
                                 {"role": role}).scalar_one_or_none()
            if role_id is None:
                raise SystemExit("Falta el rol ADMIN; ejecute primero todas las migraciones.")
            user_id = db.execute(text("""
                INSERT INTO dbo.Users(EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive,MustChangePassword)
                OUTPUT INSERTED.UserId
                VALUES (:email,:lookup,:password,:first,:last,:role,1,1)
            """), {"email": encrypt_text(email), "lookup": lookup_by_email[email],
                  "password": hash_password(DEFAULT_ADMIN_PASSWORD), "first": encrypt_text(first),
                  "last": encrypt_text(last), "role": role_id}).scalar_one()
            db.execute(text("""
                INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActionCode,NewRoleId,NewIsActive)
                VALUES (:target,'ACCOUNT_CREATED',:role,1)
            """), {"target": user_id, "role": role_id})
            default_admin_created = True
        # An older local bootstrap may already have created the fixed account
        # before the mandatory-change column existed. Require a change only
        # while that account still uses the known development credential.
        else:
            default_admin_row = db.execute(text("""
                SELECT UserId,PasswordHash,MustChangePassword FROM dbo.Users
                WHERE EmailLookupHash=:lookup
            """), {"lookup": lookup_by_email[DEFAULT_ADMIN[0]]}).mappings().first()
            if (default_admin_row and not default_admin_row["MustChangePassword"]
                    and verify_password(DEFAULT_ADMIN_PASSWORD, default_admin_row["PasswordHash"])):
                db.execute(text("UPDATE dbo.Users SET MustChangePassword=1 WHERE UserId=:id"),
                           {"id": default_admin_row["UserId"]})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise SystemExit("Conflicto de unicidad durante la inicialización; toda la transacción fue revertida.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    ids = {"institutionId": institution_id, "eventId": event_id,
           "categoryId": category_id, "tariffId": tariff_id}
    print(f"Datos locales de demostración listos: InstitutionId={institution_id}, EventId={event_id}, CategoryId={category_id}, TariffId={tariff_id}.")
    if credentials:
        print("Contraseñas aleatorias de un solo vistazo; guárdelas en el gestor de secretos local:")
        for username, role, password in credentials:
            print(f"{role}\t{username}\t{password}")
    else:
        print("Los perfiles demo ya existían; no se cambió ninguna cuenta ni se pueden recuperar contraseñas existentes.")
    if default_admin_created:
        print("Cuenta ADMIN local creada: adminTics@uta.edu.ec\tAdmin@utaTics")
        print("Es una credencial fija de desarrollo; cámbiela antes de usar una base compartida.")
    else:
        print("La cuenta ADMIN local ya existe; se conservó su contraseña actual.")
    if args.run_postman:
        if not credentials:
            raise SystemExit("Newman requiere las contraseñas originales; no se recuperan del hash de la base.")
        result = _run_postman(credentials, ids)
        if result:
            raise SystemExit(f"La colección E2E de Newman terminó con código {result}.")


if __name__ == "__main__":
    main()
