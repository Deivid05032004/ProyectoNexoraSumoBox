from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import MAX_REGULATION_BYTES
from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from app.schemas.regulation import RegulationUpdate
from app.services.regulation_storage import (
    InvalidRegulationPdf, delete_pdf, read_pdf, safe_filename, validate_pdf, write_pdf,
)
from database import get_db

router = APIRouter(tags=["Reglamentos"])


def _regulation_row(db: Session, regulation_id: int):
    return db.execute(text("""
        SELECT d.RegulationId AS id,d.EventId AS event_id,e.Name AS event_name,
          d.CategoryId AS category_id,c.Name AS category_name,d.Title AS title,
          d.VersionNumber AS version,d.OriginalFilename AS original_filename,
          d.MediaType AS media_type,d.FileSizeBytes AS file_size_bytes,d.Sha256 AS sha256,
          d.StatusCode AS status,d.EffectiveFrom AS effective_from,d.EffectiveUntil AS effective_until,
          d.UploadedByUserId AS uploaded_by_user_id,d.CreatedAt AS created_at,d.PublishedAt AS published_at
        FROM dbo.EventRegulations d JOIN dbo.Events e ON e.EventId=d.EventId
        LEFT JOIN dbo.Categories c ON c.CategoryId=d.CategoryId
        WHERE d.RegulationId=:id
    """), {"id": regulation_id}).mappings().first()


def _public_item(row):
    result = dict(row)
    result["download_url"] = f"/api/v1/regulations/{result['id']}/file"
    result.pop("uploaded_by_user_id", None)
    return result


@router.get("/api/v1/events/{event_id}/regulations")
def list_public_regulations(event_id: int, response: Response,
                            category_id: int | None = Query(default=None, gt=0),
                            page: int = Query(1, ge=1, le=1_000_000),
                            limit: int = Query(20, ge=1, le=100),
                            db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id AND IsActive=1"),
                  {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    if category_id is not None and db.execute(text(
            "SELECT 1 FROM dbo.Categories WHERE CategoryId=:id AND IsActive=1"),
            {"id": category_id}).first() is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")

    if category_id is not None:
        total = db.execute(text("""
            SELECT COUNT_BIG(*) FROM (
              SELECT TOP (1) RegulationId FROM dbo.EventRegulations
              WHERE EventId=:event AND StatusCode='PUBLISHED'
                AND EffectiveFrom<=CONVERT(date,GETDATE())
                AND (EffectiveUntil IS NULL OR EffectiveUntil>=CONVERT(date,GETDATE()))
                AND (CategoryId=:category OR CategoryId IS NULL)
              ORDER BY CASE WHEN CategoryId=:category THEN 0 ELSE 1 END,
                       EffectiveFrom DESC,VersionNumber DESC
            ) current_regulation
        """), {"event": event_id, "category": category_id}).scalar_one()
        rows = db.execute(text("""
            SELECT TOP (1) d.RegulationId AS id,d.EventId AS event_id,e.Name AS event_name,
              d.CategoryId AS category_id,c.Name AS category_name,d.Title AS title,
              d.VersionNumber AS version,d.OriginalFilename AS original_filename,
              d.MediaType AS media_type,d.FileSizeBytes AS file_size_bytes,d.Sha256 AS sha256,
              d.StatusCode AS status,d.EffectiveFrom AS effective_from,d.EffectiveUntil AS effective_until,
              d.CreatedAt AS created_at,d.PublishedAt AS published_at
            FROM dbo.EventRegulations d JOIN dbo.Events e ON e.EventId=d.EventId
            LEFT JOIN dbo.Categories c ON c.CategoryId=d.CategoryId
            WHERE d.EventId=:event AND d.StatusCode='PUBLISHED'
              AND d.EffectiveFrom<=CONVERT(date,GETDATE())
              AND (d.EffectiveUntil IS NULL OR d.EffectiveUntil>=CONVERT(date,GETDATE()))
              AND (d.CategoryId=:category OR d.CategoryId IS NULL)
            ORDER BY CASE WHEN d.CategoryId=:category THEN 0 ELSE 1 END,
                     d.EffectiveFrom DESC,d.VersionNumber DESC
        """), {"event": event_id, "category": category_id}).mappings().all()
    else:
        total = db.execute(text("""
            SELECT COUNT_BIG(*) FROM dbo.EventRegulations
            WHERE EventId=:event AND StatusCode='PUBLISHED'
              AND EffectiveFrom<=CONVERT(date,GETDATE())
              AND (EffectiveUntil IS NULL OR EffectiveUntil>=CONVERT(date,GETDATE()))
        """), {"event": event_id}).scalar_one()
        rows = db.execute(text("""
            SELECT d.RegulationId AS id,d.EventId AS event_id,e.Name AS event_name,
              d.CategoryId AS category_id,c.Name AS category_name,d.Title AS title,
              d.VersionNumber AS version,d.OriginalFilename AS original_filename,
              d.MediaType AS media_type,d.FileSizeBytes AS file_size_bytes,d.Sha256 AS sha256,
              d.StatusCode AS status,d.EffectiveFrom AS effective_from,d.EffectiveUntil AS effective_until,
              d.CreatedAt AS created_at,d.PublishedAt AS published_at
            FROM dbo.EventRegulations d JOIN dbo.Events e ON e.EventId=d.EventId
            LEFT JOIN dbo.Categories c ON c.CategoryId=d.CategoryId
            WHERE d.EventId=:event AND d.StatusCode='PUBLISHED'
              AND d.EffectiveFrom<=CONVERT(date,GETDATE())
              AND (d.EffectiveUntil IS NULL OR d.EffectiveUntil>=CONVERT(date,GETDATE()))
            ORDER BY CASE WHEN d.CategoryId IS NULL THEN 0 ELSE 1 END,c.Name,d.VersionNumber DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """), {"event": event_id, "offset": (page - 1) * limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [_public_item(row) for row in rows]


@router.get("/api/v1/regulations/{regulation_id}/file")
def download_public_regulation(regulation_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT StorageKey,Title,VersionNumber FROM dbo.EventRegulations d
        JOIN dbo.Events e ON e.EventId=d.EventId
        WHERE d.RegulationId=:id AND d.StatusCode='PUBLISHED' AND e.IsActive=1
          AND d.EffectiveFrom<=CONVERT(date,GETDATE())
          AND (d.EffectiveUntil IS NULL OR d.EffectiveUntil>=CONVERT(date,GETDATE()))
    """), {"id": regulation_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reglamento no disponible.")
    content = read_pdf(row["StorageKey"])
    if content is None:
        raise HTTPException(status_code=503, detail="No se pudo leer el reglamento.")
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="reglamento-{regulation_id}-v{row["VersionNumber"]}.pdf"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=300",
    })


@router.get("/api/v1/admin/events/{event_id}/regulations")
def list_admin_regulations(event_id: int, response: Response,
                           category_id: int | None = Query(default=None, gt=0),
                           status: str | None = Query(default=None, pattern="^(DRAFT|PUBLISHED|ARCHIVED)$"),
                           page: int = Query(1, ge=1, le=1_000_000),
                           limit: int = Query(50, ge=1, le=100),
                           _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    clauses = ["d.EventId=:event"]
    params = {"event": event_id, "offset": (page - 1) * limit, "limit": limit}
    if category_id is not None:
        clauses.append("d.CategoryId=:category")
        params["category"] = category_id
    if status:
        clauses.append("d.StatusCode=:status")
        params["status"] = status
    where = " AND ".join(clauses)
    total = db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.EventRegulations d WHERE {where}
    """), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT d.RegulationId AS id,d.EventId AS event_id,e.Name AS event_name,
          d.CategoryId AS category_id,c.Name AS category_name,d.Title AS title,
          d.VersionNumber AS version,d.OriginalFilename AS original_filename,
          d.MediaType AS media_type,d.FileSizeBytes AS file_size_bytes,d.Sha256 AS sha256,
          d.StatusCode AS status,d.EffectiveFrom AS effective_from,d.EffectiveUntil AS effective_until,
          d.UploadedByUserId AS uploaded_by_user_id,d.CreatedAt AS created_at,d.PublishedAt AS published_at
        FROM dbo.EventRegulations d JOIN dbo.Events e ON e.EventId=d.EventId
        LEFT JOIN dbo.Categories c ON c.CategoryId=d.CategoryId
        WHERE {where} ORDER BY d.CreatedAt DESC,d.RegulationId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [dict(row) for row in rows]


@router.post("/api/v1/admin/events/{event_id}/regulations", status_code=201)
async def upload_regulation(event_id: int,
                            file: UploadFile = File(...),
                            title: str = Form(..., min_length=1, max_length=200),
                            category_id: int | None = Form(default=None, gt=0),
                            effective_from: date | None = Form(default=None),
                            effective_until: date | None = Form(default=None),
                            user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    if category_id is not None and db.execute(text(
            "SELECT 1 FROM dbo.Categories WHERE CategoryId=:id AND IsActive=1"),
            {"id": category_id}).first() is None:
        raise HTTPException(status_code=422, detail="La categoría no existe o está inactiva.")
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="El título no puede quedar vacío.")
    starts = effective_from or date.today()
    if effective_until and effective_until < starts:
        raise HTTPException(status_code=422, detail="La fecha de finalización no puede ser anterior al inicio.")
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="El reglamento debe ser un PDF.")
    content = await file.read(MAX_REGULATION_BYTES + 1)
    try:
        digest, _page_count = validate_pdf(content)
    except InvalidRegulationPdf as exc:
        raise HTTPException(status_code=415, detail=str(exc))

    storage_key = write_pdf(content)
    try:
        version = db.execute(text("""
            SELECT ISNULL(MAX(VersionNumber),0)+1 FROM dbo.EventRegulations WITH (UPDLOCK,HOLDLOCK)
            WHERE EventId=:event AND (CategoryId=:category OR (CategoryId IS NULL AND :category IS NULL))
        """), {"event": event_id, "category": category_id}).scalar_one()
        row = db.execute(text("""
            INSERT INTO dbo.EventRegulations
              (EventId,CategoryId,Title,VersionNumber,OriginalFilename,StorageKey,MediaType,
               FileSizeBytes,Sha256,StatusCode,EffectiveFrom,EffectiveUntil,UploadedByUserId)
            OUTPUT INSERTED.RegulationId
            VALUES(:event,:category,:title,:version,:filename,:key,'application/pdf',
                   :size,:sha256,'DRAFT',:starts,:until,:actor)
        """), {"event": event_id, "category": category_id, "title": title,
              "version": version, "filename": safe_filename(file.filename), "key": storage_key,
              "size": len(content), "sha256": digest, "starts": starts,
              "until": effective_until, "actor": user["user_id"]}).scalar_one()
        db.execute(text("""
            INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
            VALUES(:id,:actor,'CREATED',NULL,'DRAFT')
        """), {"id": row, "actor": user["user_id"]})
        db.commit()
    except IntegrityError:
        db.rollback()
        delete_pdf(storage_key)
        raise HTTPException(status_code=409, detail="No se pudo guardar la versión del reglamento.")
    except Exception:
        db.rollback()
        delete_pdf(storage_key)
        raise
    result = _regulation_row(db, row)
    return dict(result)


@router.patch("/api/v1/admin/regulations/{regulation_id}")
def update_draft_regulation(regulation_id: int, payload: RegulationUpdate,
                            user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    row = db.execute(text("SELECT StatusCode,Title,EffectiveFrom,EffectiveUntil FROM dbo.EventRegulations WHERE RegulationId=:id"),
                     {"id": regulation_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reglamento no encontrado.")
    if row["StatusCode"] != "DRAFT":
        raise HTTPException(status_code=409, detail="Solo puede editar borradores.")
    values = {key: value for key, value in payload.model_dump(exclude_unset=True).items()}
    title = values.get("title", row["Title"])
    starts = values.get("effective_from", row["EffectiveFrom"])
    until = values.get("effective_until", row["EffectiveUntil"])
    if until is not None and until < starts:
        raise HTTPException(status_code=422, detail="La fecha de finalización no puede ser anterior al inicio.")
    updated = db.execute(text("""
        UPDATE dbo.EventRegulations SET Title=:title,EffectiveFrom=:starts,EffectiveUntil=:until
        WHERE RegulationId=:id AND StatusCode='DRAFT'
    """), {"title": title, "starts": starts, "until": until, "id": regulation_id})
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El reglamento dejó de ser un borrador.")
    db.execute(text("""
        INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
        VALUES(:id,:actor,'UPDATED','DRAFT','DRAFT')
    """), {"id": regulation_id, "actor": user["user_id"]})
    db.commit()
    return dict(_regulation_row(db, regulation_id))


@router.post("/api/v1/admin/regulations/{regulation_id}/publish")
def publish_regulation(regulation_id: int, user=Depends(require_roles("ADMIN")),
                       db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT RegulationId,EventId,CategoryId,StatusCode,EffectiveFrom,EffectiveUntil
        FROM dbo.EventRegulations WITH (UPDLOCK,ROWLOCK) WHERE RegulationId=:id
    """), {"id": regulation_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reglamento no encontrado.")
    if row["StatusCode"] != "DRAFT":
        raise HTTPException(status_code=409, detail="Solo puede publicar un borrador.")
    today = date.today()
    if row["EffectiveFrom"] > today or (row["EffectiveUntil"] and row["EffectiveUntil"] < today):
        raise HTTPException(status_code=422, detail="El reglamento debe estar vigente para publicarlo.")
    scope = "(CategoryId=:category OR (CategoryId IS NULL AND :category IS NULL))"
    previous = db.execute(text(f"""
        SELECT RegulationId FROM dbo.EventRegulations WITH (UPDLOCK,HOLDLOCK)
        WHERE EventId=:event AND {scope} AND StatusCode='PUBLISHED'
    """), {"event": row["EventId"], "category": row["CategoryId"]}).scalars().all()
    for old_id in previous:
        db.execute(text("UPDATE dbo.EventRegulations SET StatusCode='ARCHIVED' WHERE RegulationId=:id"),
                   {"id": old_id})
        db.execute(text("""
            INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
            VALUES(:id,:actor,'ARCHIVED','PUBLISHED','ARCHIVED')
        """), {"id": old_id, "actor": user["user_id"]})
    db.execute(text("""
        UPDATE dbo.EventRegulations SET StatusCode='PUBLISHED',PublishedAt=SYSUTCDATETIME()
        WHERE RegulationId=:id
    """), {"id": regulation_id})
    db.execute(text("""
        INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
        VALUES(:id,:actor,'PUBLISHED','DRAFT','PUBLISHED')
    """), {"id": regulation_id, "actor": user["user_id"]})
    db.commit()
    return dict(_regulation_row(db, regulation_id))


@router.post("/api/v1/admin/regulations/{regulation_id}/archive")
def archive_regulation(regulation_id: int, user=Depends(require_roles("ADMIN")),
                       db: Session = Depends(get_db)):
    row = db.execute(text("SELECT StatusCode FROM dbo.EventRegulations WITH (UPDLOCK,ROWLOCK) WHERE RegulationId=:id"),
                     {"id": regulation_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reglamento no encontrado.")
    if row[0] == "ARCHIVED":
        raise HTTPException(status_code=409, detail="El reglamento ya está archivado.")
    updated = db.execute(text("UPDATE dbo.EventRegulations SET StatusCode='ARCHIVED' WHERE RegulationId=:id AND StatusCode=:previous"),
                         {"id": regulation_id, "previous": row[0]})
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El estado del reglamento cambió; actualiza la vista e inténtalo de nuevo.")
    db.execute(text("""
        INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
        VALUES(:id,:actor,'ARCHIVED',:previous,'ARCHIVED')
    """), {"id": regulation_id, "actor": user["user_id"], "previous": row[0]})
    db.commit()
    return dict(_regulation_row(db, regulation_id))


@router.get("/api/v1/admin/regulations/{regulation_id}/history")
def regulation_history(regulation_id: int, response: Response,
                       page: int = Query(1, ge=1, le=1_000_000),
                       limit: int = Query(50, ge=1, le=100),
                       _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.EventRegulations WHERE RegulationId=:id"),
                  {"id": regulation_id}).first() is None:
        raise HTTPException(status_code=404, detail="Reglamento no encontrado.")
    total = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.EventRegulationHistory WHERE RegulationId=:id"),
                       {"id": regulation_id}).scalar_one()
    rows = db.execute(text("""
        SELECT HistoryId AS id,ActionCode AS action,PreviousStatus AS previous_status,
          NewStatus AS new_status,ActorUserId AS actor_user_id,ChangedAt AS changed_at
        FROM dbo.EventRegulationHistory WHERE RegulationId=:id
        ORDER BY ChangedAt DESC,HistoryId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"id": regulation_id, "offset": (page - 1) * limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [dict(row) for row in rows]
