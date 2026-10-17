
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

connection_parts = [
    f"DRIVER={{{DB_DRIVER}}};",
    f"SERVER={DB_SERVER};",
    f"DATABASE={DB_NAME};",
    "Encrypt=yes;",
    f"TrustServerCertificate={os.getenv('DB_TRUST_SERVER_CERTIFICATE', 'yes')};",
]
if DB_AUTH_MODE == "windows":
    connection_parts.append("Trusted_Connection=yes;")
elif DB_AUTH_MODE == "sql":
    if not os.getenv("DB_USERNAME") or not os.getenv("DB_PASSWORD"):
        raise RuntimeError("DB_USERNAME y DB_PASSWORD son obligatorios con DB_AUTH_MODE=sql.")
    def _odbc_value(value: str) -> str:
        return "{" + value.replace("}", "}}") + "}"

    connection_parts.extend([
        f"UID={_odbc_value(os.getenv('DB_USERNAME', ''))};",
        f"PWD={_odbc_value(os.getenv('DB_PASSWORD', ''))};",
    ])
else:
    raise RuntimeError("DB_AUTH_MODE debe ser 'windows' o 'sql'.")
connection_string = "".join(connection_parts)

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
