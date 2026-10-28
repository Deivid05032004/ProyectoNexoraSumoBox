
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", r".\SQLEXPRESS")
DB_NAME = os.getenv("DB_NAME", "UTA_SUMO_ROBOTICS_CUP")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_AUTH_MODE = os.getenv("DB_AUTH_MODE", "windows").strip().lower()

def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _make_connection_string(database: str, username: str | None = None,
                            password: str | None = None) -> str:
    parts = [
        f"DRIVER={{{DB_DRIVER}}};",
        f"SERVER={DB_SERVER};",
        f"DATABASE={database};",
        "Encrypt=yes;",
        f"TrustServerCertificate={os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')};",
    ]
    if username is not None:
        parts.extend([f"UID={_odbc_value(username)};", f"PWD={_odbc_value(password or '')};"])
    elif DB_AUTH_MODE == "windows":
        parts.append("Trusted_Connection=yes;")
    elif DB_AUTH_MODE == "sql":
        runtime_username = os.getenv("DB_USERNAME", "")
        runtime_password = os.getenv("DB_PASSWORD", "")
        if not runtime_username or not runtime_password:
            raise RuntimeError("DB_USERNAME y DB_PASSWORD son obligatorios con DB_AUTH_MODE=sql.")
        parts.extend([f"UID={_odbc_value(runtime_username)};", f"PWD={_odbc_value(runtime_password)};"])
    else:
        raise RuntimeError("DB_AUTH_MODE debe ser 'windows' o 'sql'.")
    return "".join(parts)


connection_string = _make_connection_string(DB_NAME)
migration_username = os.getenv("MIGRATION_DB_USERNAME")
migration_password = os.getenv("MIGRATION_DB_PASSWORD")
if bool(migration_username) != bool(migration_password):
    raise RuntimeError("MIGRATION_DB_USERNAME y MIGRATION_DB_PASSWORD deben configurarse juntos.")
migration_connection_string = (
    _make_connection_string(DB_NAME, migration_username, migration_password)
    if migration_username else connection_string
)

DATABASE_URL = (
    "mssql+pyodbc:///?odbc_connect="
    + quote_plus(connection_string)
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    hide_parameters=True,
)

migration_engine = create_engine(
    "mssql+pyodbc:///?odbc_connect=" + quote_plus(migration_connection_string),
    pool_pre_ping=True,
    pool_recycle=1800,
    hide_parameters=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    """Entrega una sesión por solicitud y garantiza su cierre."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def verificar_conexion():
    """Comprueba la conexión y devuelve el nombre de la base de datos."""
    with engine.connect() as connection:
        resultado = connection.execute(
            text("SELECT DB_NAME()")
        )
        return resultado.scalar_one()
