from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from app.core.pagination import apply_pagination_headers
from app.schemas.resources import EventCategoryCreateInput, EventCategoryRulesInput
from database import get_db

router = APIRouter(tags=["Categorías por evento"])

_SELECT = """
    SELECT ec.EventId AS event_id,ec.CategoryId AS category_id,c.Name AS category_name,
      c.Description AS description,ec.IsActive AS is_active,
      ec.MinParticipants AS min_participants,ec.MaxParticipants AS max_participants,
      ec.MinCoaches AS min_coaches,ec.MaxCoaches AS max_coaches,
      ec.MaxRegistrations AS max_registrations
    FROM dbo.EventCategories ec JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
"""


@router.post("/api/v1/admin/events/{event_id}/categories", status_code=201)
def create_event_category(event_id: int, payload: EventCategoryCreateInput,
                          _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    try:
        category = db.execute(text("""
            INSERT dbo.Categories(Name,Description)
            OUTPUT INSERTED.CategoryId AS id,INSERTED.Name AS name,
                   INSERTED.Description AS description
            VALUES(:name,:description)
        """), {"name": payload.name, "description": payload.description}).mappings().one()
        db.execute(text("""
            INSERT dbo.EventCategories(EventId,CategoryId,IsActive,MinParticipants,MaxParticipants,
              MinCoaches,MaxCoaches,MaxRegistrations)
            VALUES(:event,:category,:active,:min_participants,:max_participants,
              :min_coaches,:max_coaches,:max_registrations)
        """), {"event": event_id, "category": category["id"], "active": payload.is_active,
              "min_participants": payload.min_participants, "max_participants": payload.max_participants,
              "min_coaches": payload.min_coaches, "max_coaches": payload.max_coaches,
              "max_registrations": payload.max_registrations})
        db.commit()
        return {**dict(category), "event_id": event_id, "is_active": payload.is_active,
                "min_participants": payload.min_participants, "max_participants": payload.max_participants,
                "min_coaches": payload.min_coaches, "max_coaches": payload.max_coaches,
                "max_registrations": payload.max_registrations}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")


@router.get("/api/v1/events/{event_id}/categories")
def list_event_categories(event_id: int, response: Response,
                          category_id: int | None = Query(None, ge=1),
                          page: int = Query(1, ge=1, le=1_000_000),
                          limit: int = Query(5, ge=1, le=100), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id AND IsActive=1"),
                  {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    category_filter = " AND ec.CategoryId=:category" if category_id is not None else ""
    params = {"event": event_id, "category": category_id,
              "offset": (page - 1) * limit, "limit": limit}
    total = int(db.execute(text("""SELECT COUNT_BIG(*) FROM dbo.EventCategories ec
        JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
        WHERE ec.EventId=:event AND ec.IsActive=1 AND c.IsActive=1""" + category_filter),
        {"event": event_id, "category": category_id}).scalar_one())
    rows = db.execute(text(_SELECT + """
        WHERE ec.EventId=:event AND ec.IsActive=1 AND c.IsActive=1
          AND (:category IS NULL OR ec.CategoryId=:category)
        ORDER BY c.Name,c.CategoryId OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    return [dict(row) for row in rows]


@router.get("/api/v1/admin/events/{event_id}/categories")
def list_admin_event_categories(event_id: int, response: Response,
                                page: int = Query(1, ge=1, le=1_000_000),
                                limit: int = Query(5, ge=1, le=100),
                                _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    predicate = "WHERE ec.EventId=:event"
    params = {"event": event_id, "offset": (page - 1) * limit, "limit": limit}
    total = int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.EventCategories ec " + predicate),
                           {"event": event_id}).scalar_one())
    rows = db.execute(text(_SELECT + """
        WHERE ec.EventId=:event ORDER BY c.Name,c.CategoryId
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    return {"items": [dict(row) for row in rows], "page": page, "page_size": limit,
            "total": total, "total_pages": (total + limit - 1) // limit}


@router.put("/api/v1/admin/events/{event_id}/categories/{category_id}")
def set_event_category(event_id: int, category_id: int, payload: EventCategoryRulesInput,
                       _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    exists = db.execute(text("""
        SELECT 1 FROM dbo.Events e CROSS JOIN dbo.Categories c
        WHERE e.EventId=:event AND c.CategoryId=:category
    """), {"event": event_id, "category": category_id}).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="Evento o categoría no encontrada.")
    values = payload.model_dump()
    try:
        row = db.execute(text("""
            UPDATE dbo.EventCategories WITH (UPDLOCK, SERIALIZABLE)
            SET IsActive=:active,MinParticipants=:min_participants,
                MaxParticipants=:max_participants,MinCoaches=:min_coaches,
                MaxCoaches=:max_coaches,MaxRegistrations=:max_registrations,
                UpdatedAt=SYSUTCDATETIME()
            OUTPUT INSERTED.EventId AS event_id,INSERTED.CategoryId AS category_id,
                INSERTED.IsActive AS is_active,INSERTED.MinParticipants AS min_participants,
                INSERTED.MaxParticipants AS max_participants,INSERTED.MinCoaches AS min_coaches,
                INSERTED.MaxCoaches AS max_coaches,INSERTED.MaxRegistrations AS max_registrations
            WHERE EventId=:event AND CategoryId=:category
        """), {**values, "active": values["is_active"],
                "event": event_id, "category": category_id}).mappings().first()
        if row is None:
            row = db.execute(text("""
                INSERT INTO dbo.EventCategories(EventId,CategoryId,IsActive,MinParticipants,
                    MaxParticipants,MinCoaches,MaxCoaches,MaxRegistrations)
                OUTPUT INSERTED.EventId AS event_id,INSERTED.CategoryId AS category_id,
                    INSERTED.IsActive AS is_active,INSERTED.MinParticipants AS min_participants,
                    INSERTED.MaxParticipants AS max_participants,INSERTED.MinCoaches AS min_coaches,
                    INSERTED.MaxCoaches AS max_coaches,INSERTED.MaxRegistrations AS max_registrations
                VALUES(:event,:category,:is_active,:min_participants,:max_participants,
                    :min_coaches,:max_coaches,:max_registrations)
            """), {**values, "event": event_id, "category": category_id}).mappings().one()
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar la configuración de categoría del evento.")
