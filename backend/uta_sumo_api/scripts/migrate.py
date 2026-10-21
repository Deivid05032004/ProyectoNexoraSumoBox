"""Apply the checked-in SQL migrations atomically and optionally reset the local DB.

CREATE DATABASE is SQL Server's own atomic DDL operation and cannot participate
in a user transaction. Every schema/data migration after that is one transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pyodbc
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from database import DB_NAME, DB_SERVER, engine, connection_string
from app.core.crypto import (email_lookup_hash, encrypt_bytes, encrypt_text, is_encrypted,
                             decrypt_text, payment_reference_lookup_hash)
from app.core.config import RECEIPT_STORAGE_DIR

MIGRATIONS = [
    ROOT / "database/scripts/02_create_tables.sql",
    ROOT / "database/seeds/02_initial_data.sql",
    ROOT / "database/scripts/03_create_relationships.sql",
    ROOT / "database/scripts/04_create_indexes.sql",
    ROOT / "database/scripts/05_create_constraints.sql",
    ROOT / "database/scripts/06_email_encryption_upgrade.sql",
    ROOT / "database/scripts/07_email_encryption_constraints.sql",
    ROOT / "database/scripts/08_pagination_indexes.sql",
    ROOT / "database/scripts/09_google_identities.sql",
    ROOT / "database/scripts/10_competition_scoring.sql",
    ROOT / "database/scripts/11_competition_status_history.sql",
    ROOT / "database/scripts/12_finalize_roles.sql",
    ROOT / "database/scripts/13_registration_participant_positions.sql",
    ROOT / "database/scripts/14_registration_delivery.sql",
    ROOT / "database/scripts/15_registration_config_ciphertext_capacity.sql",
    ROOT / "database/scripts/16_registration_document_version.sql",
    ROOT / "database/scripts/17_admin_registration_filters.sql",
    ROOT / "database/scripts/18_event_regulations.sql",
    ROOT / "database/scripts/19_current_combat.sql",
    ROOT / "database/scripts/20_match_team_robot.sql",
]
SUPERSEDED_BASELINE_MIGRATIONS = {
    "database/scripts/02_create_tables.sql",
    "database/seeds/02_initial_data.sql",
    "database/scripts/03_create_relationships.sql",
    "database/scripts/04_create_indexes.sql",
    "database/scripts/05_create_constraints.sql",
}
GO_LINE = re.compile(r"(?im)^\s*GO\s*(?:--.*)?$")
USE_LINE = re.compile(r"(?im)^\s*USE\s+(?:\[[^]]+\]|[A-Za-z0-9_]+)\s*;?\s*$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
RESETTABLE_BASE_TABLES = {"Categories", "Roles", "RegistrationStatuses", "SchemaMigrations"}


def _database_identifier() -> str:
    if not IDENTIFIER.fullmatch(DB_NAME):
        raise SystemExit("DB_NAME solo puede contener letras, números y guion bajo.")
    return f"[{DB_NAME}]"


def _is_local_sql_server() -> bool:
    value = DB_SERVER.strip().lower()
    local_names = {".", "(local)", "localhost", "127.0.0.1"}
    machine = __import__("socket").gethostname().lower()
    return value in local_names or value.split("\\", 1)[0] in local_names | {machine}


def _master_connection_string() -> str:
    result, replaced = re.subn(r"(?i)DATABASE=[^;]+;", "DATABASE=master;", connection_string, count=1)
    if replaced != 1:
        raise SystemExit("No se pudo dirigir la conexión de SQL Server a master.")
    return result


def _batch_statements(script: str):
    for batch in GO_LINE.split(script):
        batch = USE_LINE.sub("", batch).strip()
        if batch:
            yield batch


def _execute_batch(cursor, batch: str) -> None:
    cursor.execute(batch)
    # Drain result sets from verification SELECTs so the next batch can execute.
    while cursor.description is not None:
        cursor.fetchall()
        if not cursor.nextset():
            break


def _ensure_database_exists() -> None:
    if not IDENTIFIER.fullmatch(DB_NAME):
        raise SystemExit("DB_NAME solo puede contener letras, números y guion bajo.")
    script_path = ROOT / "database/scripts/01_create_database.sql"
    source = script_path.read_text(encoding="utf-8-sig").replace(
        "UTA_SUMO_ROBOTICS_CUP", DB_NAME
    )
    with pyodbc.connect(_master_connection_string(), autocommit=True) as conn:
        cursor = conn.cursor()
        for batch in _batch_statements(source):
            _execute_batch(cursor, batch)


def _reset_database(confirm_drop: bool = False) -> None:
    if DB_NAME != "UTA_SUMO_ROBOTICS_CUP" or not _is_local_sql_server():
        raise SystemExit("El reinicio solo se permite en UTA_SUMO_ROBOTICS_CUP de una instancia local.")
    database = _database_identifier()
    with pyodbc.connect(_master_connection_string(), autocommit=True) as conn:
        cursor = conn.cursor()
        exists = cursor.execute("SELECT DB_ID(?)", DB_NAME).fetchval()
        if exists is not None:
            with pyodbc.connect(connection_string, autocommit=True) as target:
                target_cursor = target.cursor()
                table_names = [row[0] for row in target_cursor.execute(
                    "SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')")]
                protected = []
                allowed_baseline_counts = {"Categories": 1, "Roles": 3, "RegistrationStatuses": 7}
                for table_name in table_names:
                    safe_table = table_name.replace("]", "]]" )
                    count = target_cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM dbo.[{safe_table}]").fetchval()
                    if table_name not in RESETTABLE_BASE_TABLES and count:
                        protected.append((table_name, count))
                    elif table_name in allowed_baseline_counts and count > allowed_baseline_counts[table_name]:
                        protected.append((f"custom {table_name}", count))
                if "Categories" in table_names:
                    unexpected = target_cursor.execute("""
                        SELECT COUNT_BIG(*) FROM dbo.Categories
                        WHERE Name<>N'MINI SUMO RC AMATEUR'
                    """).fetchval()
                    if unexpected:
                        protected.append(("custom Categories", unexpected))
                if "Roles" in table_names:
                    unexpected = target_cursor.execute("""
                        SELECT COUNT_BIG(*) FROM dbo.Roles
                        WHERE Code NOT IN ('ADMIN','PARTICIPANT','EVENT_MANAGER')
                    """).fetchval()
                    if unexpected:
                        protected.append(("custom Roles", unexpected))
                if "RegistrationStatuses" in table_names:
                    unexpected = target_cursor.execute("""
                        SELECT COUNT_BIG(*) FROM dbo.RegistrationStatuses
                        WHERE Code NOT IN ('PENDING','PAYMENT_PENDING','PAYMENT_REVIEW',
                            'APPROVED','OBSERVED','REJECTED','CANCELLED')
                    """).fetchval()
                    if unexpected:
                        protected.append(("custom RegistrationStatuses", unexpected))
                if protected and not confirm_drop:
                    detail = ", ".join(f"{name}={count}" for name, count in protected)
                    raise SystemExit("Reinicio cancelado: hay datos operativos que deben conservarse: " + detail)
            if protected and confirm_drop:
                print("AVISO: se eliminarán los datos locales confirmados: " + ", ".join(
                    f"{name}={count}" for name, count in protected
                ))
            cursor.execute(f"IF DB_ID(N'{DB_NAME}') IS NOT NULL BEGIN ALTER DATABASE {database} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; END")
            cursor.execute(f"USE master; DROP DATABASE {database};")
        cursor.execute(f"CREATE DATABASE {database};")
    print(f"Base local recreada: {DB_NAME}")


def _ensure_migration_table() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            IF OBJECT_ID('dbo.SchemaMigrations','U') IS NULL
            BEGIN
                CREATE TABLE dbo.SchemaMigrations(
                    MigrationId NVARCHAR(260) NOT NULL PRIMARY KEY,
                    Checksum CHAR(64) NOT NULL,
                    AppliedAt DATETIME2 NOT NULL CONSTRAINT DF_SchemaMigrations_AppliedAt DEFAULT SYSUTCDATETIME()
                );
            END
        """))


def _apply_migrations() -> None:
    engine.dispose()
    _ensure_migration_table()
    for path in MIGRATIONS:
        if not path.is_file():
            raise SystemExit(f"Falta la migración requerida: {path}")
        source = path.read_text(encoding="utf-8-sig")
        checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
        migration_id = path.relative_to(ROOT).as_posix()
        with engine.connect() as conn:
            prior = conn.execute(text("SELECT Checksum FROM dbo.SchemaMigrations WHERE MigrationId=:id"),
                                 {"id": migration_id}).scalar_one_or_none()
        if prior is not None:
            if prior != checksum:
                if migration_id not in SUPERSEDED_BASELINE_MIGRATIONS:
                    raise SystemExit(f"Migración ya aplicada fue editada: {migration_id}. Cree una migración nueva.")
                print(f"BASELINE-SUPERSEDED {migration_id}; los cambios se aplican por una migración nueva.")
                continue
            print(f"SKIP {migration_id}")
            continue
        file_backups = []
        try:
            with engine.begin() as conn:
                raw = conn.connection.driver_connection.cursor()
                try:
                    for batch in _batch_statements(source):
                        _execute_batch(raw, batch)
                finally:
                    raw.close()
                if path.name == "06_email_encryption_upgrade.sql":
                    _backfill_encrypted_pii(conn, file_backups)
                conn.execute(text("""
                    INSERT INTO dbo.SchemaMigrations(MigrationId,Checksum)
                    VALUES (:id,:checksum)
                """), {"id": migration_id, "checksum": checksum})
        except Exception:
            _restore_receipt_files(file_backups)
            raise
        print(f"APPLIED {migration_id}")
    _backfill_payment_reference_hashes()


def _backfill_payment_reference_hashes() -> None:
    """Build keyed exact-match indexes for legacy encrypted transfer references."""
    with engine.begin() as conn:
        if conn.execute(text("SELECT COL_LENGTH('dbo.Payments','PaymentReferenceLookupHash')")).scalar_one() is None:
            return
        rows = conn.execute(text("""
            SELECT PaymentId,PaymentReference FROM dbo.Payments
            WHERE PaymentReference IS NOT NULL AND PaymentReferenceLookupHash IS NULL
        """)).all()
        for payment_id, encrypted_reference in rows:
            reference = decrypt_text(encrypted_reference)
            lookup_hash = payment_reference_lookup_hash(reference)
            if lookup_hash:
                conn.execute(text("""
                    UPDATE dbo.Payments SET PaymentReferenceLookupHash=:hash WHERE PaymentId=:id
                """), {"hash": lookup_hash, "id": payment_id})


def _backfill_encrypted_pii(conn, file_backups) -> None:
    """Encrypt legacy plaintext columns and local receipts in the migration transaction."""
    has_legacy_username = conn.execute(text(
        "SELECT CASE WHEN COL_LENGTH('dbo.Users','Username') IS NULL THEN 0 ELSE 1 END"
    )).scalar_one()
    if has_legacy_username:
        users = conn.execute(text("""
            SELECT u.UserId,u.Username,u.EmailCiphertext,u.EmailLookupHash,u.FirstName,u.LastName,
                   r.Code AS RoleCode
            FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        """)).mappings().all()
        fixed_emails = {
            "admin.demo": "admin.demo@example.com",
            "event_manager.demo": "event_manager.demo@example.com",
            "administrator.demo": "administrator.demo@example.com",
            "participant.demo": "participant.demo@example.com",
        }
        for row in users:
            email = row["EmailCiphertext"]
            was_legacy = not email
            if was_legacy:
                prior_username = row["Username"]
                email = fixed_emails.get(prior_username)
                if email is None:
                    email = f"legacy-user-{row['UserId']}@example.com"
                    conn.execute(text("UPDATE dbo.Users SET IsActive=0 WHERE UserId=:id"),
                                 {"id": row["UserId"]})
            elif is_encrypted(email):
                email = email
            else:
                email = email.strip().casefold()
            lookup = row["EmailLookupHash"] or email_lookup_hash(email)
            conn.execute(text("""
                UPDATE dbo.Users SET EmailCiphertext=:email,EmailLookupHash=:lookup,
                  FirstName=:first,LastName=:last WHERE UserId=:id
            """), {"id": row["UserId"], "email": encrypt_text(email), "lookup": lookup,
                  "first": encrypt_text(row["FirstName"]), "last": encrypt_text(row["LastName"])})

    fields = (
        ("Participants", "ParticipantId", ("FirstName", "LastName", "MobilePhone")),
        ("Teams", "TeamId", ("Name", "ContactPhone")),
        ("Robots", "RobotId", ("Name", "RobotDescription")),
        ("Registrations", "RegistrationId", ("Notes",)),
        ("Payments", "PaymentId", ("PaymentReference",)),
        ("StatusHistory", "HistoryId", ("Comments",)),
    )
    for table, key_column, columns in fields:
        selected = ",".join([key_column, *columns])
        rows = conn.execute(text(f"SELECT {selected} FROM dbo.{table}")).mappings().all()
        for row in rows:
            changes = {column.lower(): encrypt_text(row[column]) for column in columns
                       if row[column] is not None and not is_encrypted(row[column])}
            if changes:
                assignments = ",".join(f"{column}=:v_{column.lower()}" for column in changes)
                params = {f"v_{column}": value for column, value in changes.items()}
                params["id"] = row[key_column]
                conn.execute(text(f"UPDATE dbo.{table} SET {assignments} WHERE {key_column}=:id"), params)

    receipts = conn.execute(text("""
        SELECT ReceiptId,StorageKey,EncryptionVersion FROM dbo.PaymentReceipts WHERE EncryptionVersion=0
    """)).all()
    root = RECEIPT_STORAGE_DIR.resolve()
    for receipt_id, storage_key, _version in receipts:
        path = (root / storage_key).resolve()
        if path.parent != root or not path.is_file():
            continue
        original = path.read_bytes()
        encrypted = original if original.startswith(b"UTAENC1") else encrypt_bytes(original)
        if encrypted != original:
            staging = root / f".{path.name}.{os.urandom(8).hex()}.migrate"
            with staging.open("xb") as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            file_backups.append((path, original))
            os.replace(staging, path)
        conn.execute(text("UPDATE dbo.PaymentReceipts SET EncryptionVersion=1 WHERE ReceiptId=:id"),
                     {"id": receipt_id})


def _restore_receipt_files(file_backups) -> None:
    for path, original in reversed(file_backups):
        try:
            path.write_bytes(original)
        except OSError:
            print(f"ERROR: no se pudo restaurar el comprobante previo {path.name}; restaure desde respaldo.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-local", action="store_true",
                        help="Borra y recrea solo la instancia local de desarrollo.")
    parser.add_argument("--confirm-drop", action="store_true",
                        help="Confirma la eliminación de datos al reiniciar la base local.")
    args = parser.parse_args()
    if args.reset_local:
        if not args.confirm_drop:
            raise SystemExit("Reinicio cancelado. Verifique el destino y use --reset-local --confirm-drop para confirmar la eliminación local.")
        _reset_database(confirm_drop=args.confirm_drop)
    _ensure_database_exists()
    _apply_migrations()
    if os.getenv("AUTO_BOOTSTRAP_DEMO_ACCOUNTS", "false").strip().lower() in {"1", "true", "yes"}:
        if DB_NAME != "UTA_SUMO_ROBOTICS_CUP" or not _is_local_sql_server():
            raise SystemExit("AUTO_BOOTSTRAP_DEMO_ACCOUNTS solo se permite en la base local de desarrollo.")
        bootstrapper = API_DIR / "scripts/bootstrap_local_demo_accounts.py"
        subprocess.run([sys.executable, str(bootstrapper)], cwd=API_DIR, check=True)
    print("Migraciones aplicadas y registradas correctamente.")


if __name__ == "__main__":
    main()
