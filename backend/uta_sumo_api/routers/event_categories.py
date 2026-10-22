from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from app.schemas.resources import EventCategoryRulesInput
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


@router.get("/api/v1/events/{event_id}/categories")
def list_event_categories(event_id: int, db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id AND IsActive=1"),
                  {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    rows = db.execute(text(_SELECT + """
        WHERE ec.EventId=:event AND ec.IsActive=1 AND c.IsActive=1
        ORDER BY c.Name,c.CategoryId
    """), {"event": event_id}).mappings().all()
    return [dict(row) for row in rows]


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
