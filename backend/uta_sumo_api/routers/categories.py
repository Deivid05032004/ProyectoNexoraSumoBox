from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from database import engine

router = APIRouter(
    prefix="/api/v1/categories",
    tags=["Categorías"],
)


@router.get("")
def listar_categorias():
    query = text("""
        SELECT
            CategoryId AS id,
            Name AS name,
            Description AS description
        FROM dbo.Categories
        WHERE IsActive = 1
        ORDER BY Name;
    """)

    try:
        with engine.connect() as connection:
            rows = connection.execute(query).mappings().all()

        return [dict(row) for row in rows]

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudieron consultar las categorías.",
        )
