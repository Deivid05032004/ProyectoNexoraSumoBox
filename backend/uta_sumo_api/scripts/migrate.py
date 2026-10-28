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
from sqlalchemy import LargeBinary, bindparam, text

ROOT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from database import (DB_AUTH_MODE, DB_NAME, DB_SERVER, migration_connection_string,
                      migration_engine)
from app.core.crypto import (email_lookup_hash, encrypt_bytes, encrypt_text, is_encrypted,
                             decrypt_text, payment_reference_lookup_hash,
                             resource_name_lookup_hash, normalize_resource_name)
from app.core.config import RECEIPT_STORAGE_DIR, REGULATION_STORAGE_DIR

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
    ROOT / "database/scripts/21_uta_sumo_robotics_cup_2026.sql",
    ROOT / "database/scripts/22_event_category_rules.sql",
    ROOT / "database/scripts/23_official_event_category_rules.sql",
    ROOT / "database/scripts/24_combat_public_details.sql",
    ROOT / "database/scripts/25_registration_roster_and_match_timer.sql",
    ROOT / "database/scripts/26_enable_match_timer_by_default.sql",
    ROOT / "database/scripts/27_match_timer_direction.sql",
    ROOT / "database/scripts/28_start_clock_for_live_active_match.sql",
    ROOT / "database/scripts/29_resource_name_lookup_hashes.sql",
    ROOT / "database/scripts/30_unique_resource_names.sql",
    ROOT / "database/scripts/31_regulations_database_content.sql",
    ROOT / "database/scripts/32_finalize_regulations_database_content.sql",
    ROOT / "database/scripts/33_event_management_forms.sql",
    ROOT / "database/scripts/34_event_management_audit.sql",
    ROOT / "database/scripts/35_schedule_official_2026_event.sql",
    ROOT / "database/scripts/36_admin_password_change_required.sql",
    ROOT / "database/scripts/37_tournament_groups_and_live_dohyos.sql",
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
    host = value.split(",", 1)[0].removeprefix("tcp:").strip()
    return host in local_names or host.split("\\", 1)[0] in local_names | {machine}


def _master_connection_string() -> str:
    result, replaced = re.subn(r"(?i)DATABASE=[^;]+;", "DATABASE=master;", migration_connection_string, count=1)
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
        if DB_AUTH_MODE == "sql" and os.getenv("DB_USERNAME"):
            _ensure_runtime_principal(cursor)


def _ensure_runtime_principal(cursor) -> None:
    """Create a restricted SQL principal for the API, separate from the migrator."""
    username = os.getenv("DB_USERNAME", "").strip()
    password = os.getenv("DB_PASSWORD", "")
    if (not IDENTIFIER.fullmatch(username) or username.casefold() in {"sa", "dbo", "guest", "sys"}
            or not password):
        raise SystemExit("DB_USERNAME debe ser un identificador SQL válido y DB_PASSWORD no puede estar vacío.")
    login = f"[{username}]"
    escaped_username = username.replace("'", "''")
    escaped_password = password.replace("'", "''")
    database = _database_identifier()
    cursor.execute(f"IF SUSER_ID(N'{escaped_username}') IS NULL CREATE LOGIN {login} WITH PASSWORD=N'{escaped_password}', CHECK_POLICY=ON; ELSE ALTER LOGIN {login} WITH PASSWORD=N'{escaped_password}', CHECK_POLICY=ON;")
    cursor.execute(f"USE {database}; IF USER_ID(N'{escaped_username}') IS NULL CREATE USER {login} FOR LOGIN {login}; ELSE ALTER USER {login} WITH LOGIN={login};")
    cursor.execute(f"IF NOT EXISTS (SELECT 1 FROM sys.database_role_members drm JOIN sys.database_principals r ON r.principal_id=drm.role_principal_id JOIN sys.database_principals u ON u.principal_id=drm.member_principal_id WHERE r.name=N'db_datareader' AND u.name=N'{escaped_username}') ALTER ROLE [db_datareader] ADD MEMBER {login};")
    cursor.execute(f"IF NOT EXISTS (SELECT 1 FROM sys.database_role_members drm JOIN sys.database_principals r ON r.principal_id=drm.role_principal_id JOIN sys.database_principals u ON u.principal_id=drm.member_principal_id WHERE r.name=N'db_datawriter' AND u.name=N'{escaped_username}') ALTER ROLE [db_datawriter] ADD MEMBER {login};")


def _reset_database(confirm_drop: bool = False) -> None:
    if DB_NAME != "UTA_SUMO_ROBOTICS_CUP" or not _is_local_sql_server():
        raise SystemExit("El reinicio solo se permite en UTA_SUMO_ROBOTICS_CUP de una instancia local.")
    database = _database_identifier()
    with pyodbc.connect(_master_connection_string(), autocommit=True) as conn:
        cursor = conn.cursor()
        exists = cursor.execute("SELECT DB_ID(?)", DB_NAME).fetchval()
        if exists is not None:
            with pyodbc.connect(migration_connection_string, autocommit=True) as target:
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
    with migration_engine.begin() as conn:
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
    migration_engine.dispose()
    _ensure_migration_table()
    for path in MIGRATIONS:
        if not path.is_file():
            raise SystemExit(f"Falta la migración requerida: {path}")
        source = path.read_text(encoding="utf-8-sig")
        checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
        migration_id = path.relative_to(ROOT).as_posix()
        with migration_engine.connect() as conn:
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
        regulation_file_cleanup = []
        try:
            with migration_engine.begin() as conn:
                raw = conn.connection.driver_connection.cursor()
                try:
                    for batch in _batch_statements(source):
                        _execute_batch(raw, batch)
                finally:
                    raw.close()
                if path.name == "06_email_encryption_upgrade.sql":
                    _backfill_encrypted_pii(conn, file_backups)
                if path.name == "29_resource_name_lookup_hashes.sql":
                    _backfill_resource_name_hashes(conn)
                if path.name == "31_regulations_database_content.sql":
                    regulation_file_cleanup = _backfill_regulation_file_content(conn)
                conn.execute(text("""
                    INSERT INTO dbo.SchemaMigrations(MigrationId,Checksum)
                    VALUES (:id,:checksum)
                """), {"id": migration_id, "checksum": checksum})
        except Exception:
            _restore_receipt_files(file_backups)
            raise
        for legacy_file in regulation_file_cleanup:
            legacy_file.unlink(missing_ok=True)
        print(f"APPLIED {migration_id}")
    _backfill_payment_reference_hashes()
    _cleanup_legacy_regulation_files()


def _backfill_payment_reference_hashes() -> None:
    """Build keyed exact-match indexes for legacy encrypted transfer references."""
    with migration_engine.begin() as conn:
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


def _backfill_resource_name_hashes(conn) -> None:
    """Backfill unique, keyed name indexes and refuse ambiguous legacy names."""
    for table, id_column, resource_type in (
        ("Teams", "TeamId", "team"), ("Robots", "RobotId", "robot"),
    ):
        rows = conn.execute(text(
            f"SELECT {id_column},Name FROM dbo.{table} ORDER BY {id_column}"
        )).all()
        seen: dict[str, int] = {}
        duplicates: list[tuple[int, int]] = []
        pending: list[tuple[int, str]] = []
        empty_ids: list[int] = []
        for record_id, encrypted_name in rows:
            name = (decrypt_text(encrypted_name) or "").strip()
            if not normalize_resource_name(name):
                empty_ids.append(record_id)
                continue
            lookup_hash = resource_name_lookup_hash(name, resource_type)
            prior_id = seen.get(lookup_hash)
            if prior_id is not None:
                duplicates.append((prior_id, record_id))
            else:
                seen[lookup_hash] = record_id
            pending.append((record_id, lookup_hash))
        if empty_ids:
            raise RuntimeError(
                f"Migración de nombres detenida: {table} contiene nombres vacíos en IDs {empty_ids[:10]}. "
                "Corríjalos antes de reintentar."
            )
        if duplicates:
            raise RuntimeError(
                f"Migración de nombres detenida: {table} ya contiene nombres duplicados "
                f"(pares de IDs {duplicates[:10]}). Renombre los registros duplicados conservando sus "
                "inscripciones y vuelva a ejecutar la migración."
            )
        for record_id, lookup_hash in pending:
            conn.execute(text(
                f"UPDATE dbo.{table} SET NameLookupHash=:hash WHERE {id_column}=:id"
            ), {"hash": lookup_hash, "id": record_id})


def _backfill_regulation_file_content(conn):
    """Move legacy encrypted regulation PDFs into SQL Server before dropping paths."""
    from app.core.crypto import decrypt_bytes

    root = REGULATION_STORAGE_DIR.resolve()
    rows = conn.execute(text("""
        SELECT RegulationId,StorageKey,FileSizeBytes,Sha256,FileContent
        FROM dbo.EventRegulations ORDER BY RegulationId
    """)).mappings().all()
    cleanup = []
    for row in rows:
        if row["FileContent"] is not None:
            continue
        key = row["StorageKey"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}\.pdf\.enc", key):
            raise RuntimeError(
                f"Reglamento {row['RegulationId']} tiene una referencia de archivo local inválida; "
                "no se modificó la base."
            )
        legacy_path = (root / key).resolve()
        if legacy_path.parent != root or not legacy_path.is_file():
            raise RuntimeError(
                f"Falta el PDF local del reglamento {row['RegulationId']}; "
                "se conserva la migración pendiente y la base no se modifica."
            )
        try:
            plaintext = decrypt_bytes(legacy_path.read_bytes())
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo descifrar el PDF local del reglamento {row['RegulationId']}; "
                "se conserva el archivo y no se modifica la base."
            ) from exc
        digest = hashlib.sha256(plaintext).hexdigest()
        if len(plaintext) != row["FileSizeBytes"] or digest.lower() != row["Sha256"].strip().lower():
            raise RuntimeError(
                f"El tamaño o SHA-256 del reglamento {row['RegulationId']} no coincide; "
                "se conserva el archivo y no se modifica la base."
            )
        conn.execute(text("""
            UPDATE dbo.EventRegulations SET FileContent=:content WHERE RegulationId=:id
        """).bindparams(bindparam("content", type_=LargeBinary)),
            {"content": encrypt_bytes(plaintext), "id": row["RegulationId"]})
        cleanup.append(legacy_path)
    return cleanup


def _cleanup_legacy_regulation_files() -> None:
    """Remove managed legacy copies only after SQL Server owns every PDF."""
    with migration_engine.connect() as conn:
        if conn.execute(text("SELECT OBJECT_ID('dbo.EventRegulations','U')")).scalar_one_or_none() is None:
            return
        has_content = conn.execute(text(
            "SELECT CASE WHEN COL_LENGTH('dbo.EventRegulations','FileContent') IS NULL THEN 0 ELSE 1 END"
        )).scalar_one()
        has_legacy_key = conn.execute(text(
            "SELECT CASE WHEN COL_LENGTH('dbo.EventRegulations','StorageKey') IS NULL THEN 0 ELSE 1 END"
        )).scalar_one()
        if not has_content or has_legacy_key:
            return
        missing = conn.execute(text(
            "SELECT COUNT_BIG(*) FROM dbo.EventRegulations WHERE FileContent IS NULL"
        )).scalar_one()
    if missing:
        return
    root = REGULATION_STORAGE_DIR.resolve()
    if not root.is_dir():
        return
    for candidate in root.glob("*.pdf.enc"):
        resolved = candidate.resolve()
        if (resolved.parent == root and candidate.is_file()
                and re.fullmatch(r"[a-f0-9]{32}\.pdf\.enc", candidate.name)):
            candidate.unlink()


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
