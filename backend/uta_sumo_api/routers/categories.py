from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from app.core.pagination import apply_pagination_headers
from app.schemas.resources import CategoryInput
from database import get_db

router = APIRouter(
    prefix="/api/v1/categories",
    tags=["Categorías"],
)


@router.get("")
def listar_categorias(response: Response, page: int = Query(1, ge=1, le=1_000_000),
                     limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    query = text("""
        SELECT
            CategoryId AS id,
            Name AS name,
            Description AS description
        FROM dbo.Categories
        WHERE IsActive = 1
        ORDER BY Name, CategoryId OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """)

    try:
        total = int(db.execute(text(
            "SELECT COUNT_BIG(*) FROM dbo.Categories WHERE IsActive=1"
        )).scalar_one())
        rows = db.execute(query, {"offset": (page - 1) * limit,
                                  "limit": limit}).mappings().all()
        apply_pagination_headers(response, total=total, page=page, limit=limit)

        return [dict(row) for row in rows]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="No se pudieron consultar las categorías.",
        )


@router.get("/{category_id}")
def consultar_categoria(category_id: int, db: Session = Depends(get_db)):
    query = text("""
        SELECT CategoryId AS id, Name AS name, Description AS description
        FROM dbo.Categories WHERE CategoryId=:category_id AND IsActive=1
    """)
    try:
        row = db.execute(query, {"category_id": category_id}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Categoría no encontrada.")
        return dict(row)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="No se pudo consultar la categoría.")


@router.post("", status_code=201, dependencies=[Depends(require_roles("ADMIN"))])
def crear_categoria(payload: CategoryInput, db: Session = Depends(get_db)):
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Categories (Name, Description)
            OUTPUT INSERTED.CategoryId AS id, INSERTED.Name AS name,
                   INSERTED.Description AS description
            VALUES (:name, :description)
        """), {"name": payload.name.strip(), "description": payload.description}).mappings().one()
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")


@router.put("/{category_id}", dependencies=[Depends(require_roles("ADMIN"))])
def actualizar_categoria(category_id: int, payload: CategoryInput, db: Session = Depends(get_db)):
    try:
        row = db.execute(text("""
            UPDATE dbo.Categories SET Name=:name, Description=:description
            OUTPUT INSERTED.CategoryId AS id, INSERTED.Name AS name,
                   INSERTED.Description AS description
            WHERE CategoryId=:id
        """), {"id": category_id, "name": payload.name.strip(),
              "description": payload.description}).mappings().first()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Categoría no encontrada.")
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")


@router.patch("/{category_id}/status", dependencies=[Depends(require_roles("ADMIN"))])
def cambiar_estado_categoria(category_id: int, is_active: bool, db: Session = Depends(get_db)):
    row = db.execute(text("""
        UPDATE dbo.Categories SET IsActive=:active
        OUTPUT INSERTED.CategoryId AS id, INSERTED.IsActive AS is_active
        WHERE CategoryId=:id
    """), {"id": category_id, "active": is_active}).mappings().first()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")
    db.commit()
    return dict(row)
