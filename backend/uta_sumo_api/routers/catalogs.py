from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from app.core.pagination import apply_pagination_headers
from app.schemas.resources import EventInput, InstitutionInput, TariffInput
from database import get_db

router = APIRouter(prefix="/api/v1", tags=["Catálogos"])


def _read_page(db, query, count_query, params, page, limit, response):
    try:
        total = int(db.execute(count_query, params).scalar_one())
        rows = db.execute(query, {**params, "offset": (page - 1) * limit,
                                  "limit": limit}).mappings().all()
        apply_pagination_headers(response, total=total, page=page, limit=limit)
        return [dict(row) for row in rows]
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="No se pudo consultar el catálogo.")


def _read_all(db, query, params=None):
    try:
        return [dict(row) for row in db.execute(query, params or {}).mappings().all()]
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="No se pudo consultar el catálogo.")


@router.get("/institutions")
def institutions(response: Response, page: int = Query(1, ge=1, le=1_000_000),
                 limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return _read_page(db, text("""
        SELECT InstitutionId AS id, Name AS name
        FROM dbo.Institutions WHERE IsActive=1 ORDER BY Name
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), text("SELECT COUNT_BIG(*) FROM dbo.Institutions WHERE IsActive=1"),
        {}, page, limit, response)


@router.get("/institutions/{institution_id}")
def institution(institution_id: int, db: Session = Depends(get_db)):
    rows = _read_all(db, text("""
        SELECT InstitutionId AS id, Name AS name
        FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1
    """), {"id": institution_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Institución no encontrada.")
    return rows[0]


@router.get("/events")
def events(response: Response, page: int = Query(1, ge=1, le=1_000_000),
           limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return _read_page(db, text("""
        SELECT EventId AS id, Name AS name, EditionYear AS edition_year, CompetitionStatus AS competition_status,
               RegistrationStart AS registration_start,
               RegistrationEnd AS registration_end
        FROM dbo.Events WHERE IsActive=1 ORDER BY EditionYear DESC, Name, EventId
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), text("SELECT COUNT_BIG(*) FROM dbo.Events WHERE IsActive=1"),
        {}, page, limit, response)


@router.get("/events/{event_id}")
def event(event_id: int, db: Session = Depends(get_db)):
    rows = _read_all(db, text("""
        SELECT EventId AS id, Name AS name, EditionYear AS edition_year, CompetitionStatus AS competition_status,
               RegistrationStart AS registration_start,
               RegistrationEnd AS registration_end
        FROM dbo.Events WHERE EventId=:id AND IsActive=1
    """), {"id": event_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    return rows[0]


@router.get("/tariffs")
def tariffs(response: Response, event_id: int | None = None, category_id: int | None = None,
            page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
            db: Session = Depends(get_db)):
    predicates = [
        "t.IsActive=1", "t.ValidFrom<=CONVERT(date,GETDATE())",
        "(t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))",
        "e.IsActive=1", "c.IsActive=1",
    ]
    params = {}
    if event_id is not None:
        predicates.append("t.EventId=:event_id")
        params["event_id"] = event_id
    if category_id is not None:
        predicates.append("t.CategoryId=:category_id")
        params["category_id"] = category_id
    where = "WHERE " + " AND ".join(predicates)
    page_query = f"""
        SELECT t.TariffId AS id, t.EventId AS event_id,
               t.CategoryId AS category_id, t.Amount AS amount,
               t.ValidFrom AS valid_from, t.ValidUntil AS valid_until
        FROM dbo.Tariffs t
        JOIN dbo.Events e ON e.EventId=t.EventId
        JOIN dbo.Categories c ON c.CategoryId=t.CategoryId
        {where}
        ORDER BY t.EventId, t.CategoryId, t.TariffId
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """
    count_query = f"""
        SELECT COUNT_BIG(*)
        FROM dbo.Tariffs t
        JOIN dbo.Events e ON e.EventId=t.EventId
        JOIN dbo.Categories c ON c.CategoryId=t.CategoryId
        {where}
    """
    params.update({"offset": (page - 1) * limit, "limit": limit})
    return _read_page(db, text(page_query), text(count_query), params, page, limit, response)


@router.post("/institutions", status_code=201, dependencies=[Depends(require_roles("ADMIN"))])
def create_institution(payload: InstitutionInput, db: Session = Depends(get_db)):
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Institutions (Name) OUTPUT INSERTED.InstitutionId AS id,
            INSERTED.Name AS name VALUES (:name)
        """), {"name": payload.name.strip()}).mappings().one()
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una institución con ese nombre.")


@router.put("/institutions/{institution_id}", dependencies=[Depends(require_roles("ADMIN"))])
def update_institution(institution_id: int, payload: InstitutionInput, db: Session = Depends(get_db)):
    try:
        row = db.execute(text("""
            UPDATE dbo.Institutions SET Name=:name
            OUTPUT INSERTED.InstitutionId AS id, INSERTED.Name AS name
            WHERE InstitutionId=:id
        """), {"id": institution_id, "name": payload.name.strip()}).mappings().first()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Institución no encontrada.")
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una institución con ese nombre.")


@router.patch("/institutions/{institution_id}/status", dependencies=[Depends(require_roles("ADMIN"))])
def set_institution_status(institution_id: int, is_active: bool, db: Session = Depends(get_db)):
    row = db.execute(text("""
        UPDATE dbo.Institutions SET IsActive=:active
        OUTPUT INSERTED.InstitutionId AS id, INSERTED.IsActive AS is_active
        WHERE InstitutionId=:id
    """), {"id": institution_id, "active": is_active}).mappings().first()
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Institución no encontrada.")
    db.commit()
    return dict(row)


@router.post("/events", status_code=201, dependencies=[Depends(require_roles("ADMIN", "EVENT_MANAGER"))])
def create_event(payload: EventInput, db: Session = Depends(get_db)):
    if payload.registration_start and payload.registration_end and payload.registration_end < payload.registration_start:
        raise HTTPException(status_code=422, detail="El fin de inscripción precede al inicio.")
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Events (Name, EditionYear, RegistrationStart, RegistrationEnd, IsActive)
            OUTPUT INSERTED.EventId AS id, INSERTED.Name AS name,
                   INSERTED.EditionYear AS edition_year,
                   INSERTED.RegistrationStart AS registration_start,
                   INSERTED.RegistrationEnd AS registration_end,
                   INSERTED.IsActive AS is_active
            VALUES (:name, :year, :start, :end, :active)
        """), {"name": payload.name.strip(), "year": payload.edition_year,
              "start": payload.registration_start, "end": payload.registration_end,
              "active": payload.is_active}).mappings().one()
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe el evento para ese año.")


@router.put("/events/{event_id}", dependencies=[Depends(require_roles("ADMIN", "EVENT_MANAGER"))])
def update_event(event_id: int, payload: EventInput, db: Session = Depends(get_db)):
    if payload.registration_start and payload.registration_end and payload.registration_end < payload.registration_start:
        raise HTTPException(status_code=422, detail="El fin de inscripción precede al inicio.")
    try:
        row = db.execute(text("""
            UPDATE dbo.Events SET Name=:name, EditionYear=:year, RegistrationStart=:start,
              RegistrationEnd=:end, IsActive=:active
            OUTPUT INSERTED.EventId AS id, INSERTED.Name AS name,
              INSERTED.EditionYear AS edition_year, INSERTED.RegistrationStart AS registration_start,
              INSERTED.RegistrationEnd AS registration_end, INSERTED.IsActive AS is_active
            WHERE EventId=:id
        """), {"id": event_id, "name": payload.name.strip(), "year": payload.edition_year,
              "start": payload.registration_start, "end": payload.registration_end,
              "active": payload.is_active}).mappings().first()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Evento no encontrado.")
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe el evento para ese año.")


@router.post("/tariffs", status_code=201, dependencies=[Depends(require_roles("ADMIN"))])
def create_tariff(payload: TariffInput, db: Session = Depends(get_db)):
    if payload.valid_until and payload.valid_until < payload.valid_from:
        raise HTTPException(status_code=422, detail="La vigencia final precede al inicio.")
    exists = db.execute(text("""
        SELECT 1 FROM dbo.Events e JOIN dbo.Categories c ON c.CategoryId=:category
        WHERE e.EventId=:event AND e.IsActive=1 AND c.IsActive=1
    """), {"event": payload.event_id, "category": payload.category_id}).first()
    if not exists:
        raise HTTPException(status_code=422, detail="Evento o categoría inexistente/inactivo.")
    row = db.execute(text("""
        INSERT INTO dbo.Tariffs (EventId, CategoryId, Amount, ValidFrom, ValidUntil, IsActive)
        OUTPUT INSERTED.TariffId AS id, INSERTED.EventId AS event_id,
          INSERTED.CategoryId AS category_id, INSERTED.Amount AS amount,
          INSERTED.ValidFrom AS valid_from, INSERTED.ValidUntil AS valid_until,
          INSERTED.IsActive AS is_active
        VALUES (:event, :category, :amount, :valid_from, :valid_until, :active)
    """), {"event": payload.event_id, "category": payload.category_id,
          "amount": payload.amount, "valid_from": payload.valid_from,
          "valid_until": payload.valid_until, "active": payload.is_active}).mappings().one()
    db.commit()
    return dict(row)


@router.put("/tariffs/{tariff_id}", dependencies=[Depends(require_roles("ADMIN"))])
def update_tariff(tariff_id: int, payload: TariffInput, db: Session = Depends(get_db)):
    if payload.valid_until and payload.valid_until < payload.valid_from:
        raise HTTPException(status_code=422, detail="La vigencia final precede al inicio.")
    related = db.execute(text("""
        SELECT 1 FROM dbo.Events e JOIN dbo.Categories c ON c.CategoryId=:category
        WHERE e.EventId=:event AND e.IsActive=1 AND c.IsActive=1
    """), {"event": payload.event_id, "category": payload.category_id}).first()
    if payload.is_active and not related:
        raise HTTPException(status_code=422, detail="Evento o categoría inexistente/inactivo.")
    try:
        row = db.execute(text("""
            UPDATE dbo.Tariffs SET EventId=:event, CategoryId=:category, Amount=:amount,
              ValidFrom=:valid_from, ValidUntil=:valid_until, IsActive=:active
            OUTPUT INSERTED.TariffId AS id, INSERTED.EventId AS event_id,
              INSERTED.CategoryId AS category_id, INSERTED.Amount AS amount,
              INSERTED.ValidFrom AS valid_from, INSERTED.ValidUntil AS valid_until,
              INSERTED.IsActive AS is_active
            WHERE TariffId=:id
        """), {"id": tariff_id, "event": payload.event_id,
              "category": payload.category_id, "amount": payload.amount,
              "valid_from": payload.valid_from, "valid_until": payload.valid_until,
              "active": payload.is_active}).mappings().first()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="Tarifa no encontrada.")
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=422, detail="Evento o categoría inválido.")
