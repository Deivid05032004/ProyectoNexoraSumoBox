"""Administrative event lifecycle and versioned registration forms."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from app.schemas.resources import EventInput, EventFormInput, EventStatusInput
from database import get_db

router = APIRouter(prefix="/api/v1", tags=["Gestión de eventos"])
TRANSITIONS = {
    "DRAFT": {"SCHEDULED", "CANCELLED"},
    "SCHEDULED": {"LIVE", "CANCELLED"},
    "LIVE": {"PAUSED", "FINISHED", "CANCELLED"},
    "PAUSED": {"LIVE", "FINISHED", "CANCELLED"},
    "FINISHED": set(), "CANCELLED": set(),
}


def _event_dump(payload: EventInput):
    if not payload.name.strip():
        raise HTTPException(422, "El nombre del evento no puede quedar vacío.")
    if payload.registration_start and payload.registration_end and payload.registration_end < payload.registration_start:
        raise HTTPException(422, "El fin de inscripción precede al inicio.")
    try:
        start = datetime.fromisoformat(payload.starts_at) if payload.starts_at else None
        end = datetime.fromisoformat(payload.ends_at) if payload.ends_at else None
    except ValueError as exc:
        raise HTTPException(422, "Las fechas del evento deben usar formato ISO 8601.") from exc
    if start and end and end <= start:
        raise HTTPException(422, "El cierre del evento debe ser posterior al inicio.")
    # Registration must close before the competition starts. Compare dates in
    # the event's submitted local representation before normalizing timestamps.
    event_start_date = start.date() if start else None
    if (payload.registration_start and payload.registration_end
            and payload.registration_end < payload.registration_start):
        raise HTTPException(422, "El cierre de inscripciones debe ser posterior o igual a su inicio.")
    if payload.registration_start and event_start_date and payload.registration_start > event_start_date:
        raise HTTPException(422, "Las inscripciones no pueden iniciar después del comienzo del evento.")
    if payload.registration_end and event_start_date and payload.registration_end > event_start_date:
        raise HTTPException(422, "Las inscripciones deben cerrar antes del comienzo del evento.")
    if start and start.tzinfo:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    if end and end.tzinfo:
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
    return {**payload.model_dump(), "name": payload.name.strip(),
            "description": payload.description.strip() if payload.description else None,
            "venue": payload.venue.strip() if payload.venue else None,
            "starts_at": start, "ends_at": end}


@router.get("/admin/events")
def list_events(response: Response, search: str | None = Query(None, max_length=150),
                status: str | None = Query(None, pattern="^(DRAFT|SCHEDULED|LIVE|PAUSED|FINISHED|CANCELLED)$"),
                active_only: bool = Query(False),
                page: int = Query(1, ge=1), limit: int = Query(5, ge=1, le=100),
                _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    where = "WHERE (:search IS NULL OR e.Name LIKE :pattern) AND (:status IS NULL OR e.CompetitionStatus=:status) AND (:active_only=0 OR e.IsActive=1)"
    params = {"search": search.strip() if search else None,
              "pattern": f"%{search.strip()}%" if search else None, "status": status,
              "active_only": active_only}
    total = int(db.execute(text(f"SELECT COUNT_BIG(*) FROM dbo.Events e {where}"), params).scalar_one())
    rows = db.execute(text(f"""
      SELECT e.EventId AS id,e.Name AS name,e.EditionYear AS edition_year,e.Description AS description,
        e.Venue AS venue,e.RegistrationStart AS registration_start,e.RegistrationEnd AS registration_end,
        e.StartsAt AS starts_at,e.EndsAt AS ends_at,e.IsActive AS is_active,
        e.CompetitionStatus AS status,
        (SELECT COUNT_BIG(*) FROM dbo.Registrations r WHERE r.EventId=e.EventId) AS registrations_count
      FROM dbo.Events e {where}
      ORDER BY e.EditionYear DESC,e.EventId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {**params,"offset":(page-1)*limit,"limit":limit}).mappings().all()
    apply_pagination_headers(response,total=total,page=page,limit=limit)
    return {"items":[dict(x) for x in rows],"page":page,"page_size":limit,
            "total":total,"total_pages":(total+limit-1)//limit}


@router.post("/admin/events",status_code=201)
def create_event(payload: EventInput,user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    values=_event_dump(payload)
    try:
        row=db.execute(text("""
          INSERT dbo.Events(Name,EditionYear,Description,Venue,RegistrationStart,RegistrationEnd,
            StartsAt,EndsAt,IsActive,CompetitionStatus)
          OUTPUT INSERTED.EventId AS id,INSERTED.Name AS name,INSERTED.EditionYear AS edition_year,
            INSERTED.CompetitionStatus AS status
          VALUES(:name,:edition_year,:description,:venue,:registration_start,:registration_end,
            :starts_at,:ends_at,0,'DRAFT')
        """),values).mappings().one()
        db.execute(text("INSERT dbo.EventStatusHistory(EventId,NewStatus,Reason,ActorUserId) VALUES(:id,'DRAFT',N'Evento creado',:actor)"),
                   {"id":row["id"],"actor":user["user_id"]})
        db.execute(text("""INSERT dbo.EventManagementAudit(EventId,ActorUserId,ActionCode,NewDataJson)
          VALUES(:id,:actor,'CREATED',:data)"""),
          {"id":row["id"],"actor":user["user_id"],"data":json.dumps({k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in values.items() if k!='is_active'}|{"is_active":False},ensure_ascii=False)})
        db.commit();return dict(row)
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Ya existe un evento con ese nombre y edición.")


@router.get("/admin/events/{event_id}")
def get_admin_event(event_id:int,_user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    row=db.execute(text("""SELECT e.EventId AS id,e.Name AS name,e.EditionYear AS edition_year,
      e.Description AS description,e.Venue AS venue,e.RegistrationStart AS registration_start,
      e.RegistrationEnd AS registration_end,e.StartsAt AS starts_at,e.EndsAt AS ends_at,
      e.IsActive AS is_active,e.CompetitionStatus AS status,
      COALESCE(cfg.IsEnabled,CAST(1 AS bit)) AS registration_enabled,
      CAST(CASE WHEN EXISTS (
        SELECT 1 FROM dbo.EventCategories ec
        JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId AND c.IsActive=1
        JOIN dbo.Tariffs t ON t.EventId=ec.EventId AND t.CategoryId=ec.CategoryId
          AND t.IsActive=1
          AND t.ValidFrom<=CONVERT(date,GETDATE())
          AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
        WHERE ec.EventId=e.EventId AND ec.IsActive=1
      ) THEN 1 ELSE 0 END AS bit) AS has_active_category_tariff,
      CAST(CASE WHEN e.IsActive=1 AND COALESCE(cfg.IsEnabled,1)=1
        AND (e.RegistrationStart IS NULL OR e.RegistrationStart<=CONVERT(date,GETDATE()))
        AND (e.RegistrationEnd IS NULL OR e.RegistrationEnd>=CONVERT(date,GETDATE()))
        AND EXISTS (
          SELECT 1 FROM dbo.EventCategories ec
          JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId AND c.IsActive=1
          JOIN dbo.Tariffs t ON t.EventId=ec.EventId AND t.CategoryId=ec.CategoryId
            AND t.IsActive=1 AND t.ValidFrom<=CONVERT(date,GETDATE())
            AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
          WHERE ec.EventId=e.EventId AND ec.IsActive=1
        ) THEN 1 ELSE 0 END AS bit) AS registration_open
      FROM dbo.Events e LEFT JOIN dbo.EventRegistrationConfigs cfg ON cfg.EventId=e.EventId
      WHERE e.EventId=:id"""),
      {"id":event_id}).mappings().first()
    if not row: raise HTTPException(404,"Evento no encontrado.")
    result=dict(row)
    result["categories"]=[dict(x) for x in db.execute(text("""SELECT ec.CategoryId AS id,c.Name AS name,
      ec.IsActive AS is_active,ec.MinParticipants AS min_participants,ec.MaxParticipants AS max_participants,
      ec.MinCoaches AS min_coaches,ec.MaxCoaches AS max_coaches,ec.MaxRegistrations AS max_registrations
      FROM dbo.EventCategories ec JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
      WHERE ec.EventId=:id ORDER BY c.Name"""),{"id":event_id}).mappings().all()]
    result["form"]=current_form(db,event_id)
    return result


@router.put("/admin/events/{event_id}")
def update_event(event_id:int,payload:EventInput,user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    values=_event_dump(payload);values["id"]=event_id
    try:
        old=db.execute(text("""SELECT Name AS name,EditionYear AS edition_year,Description AS description,
          Venue AS venue,RegistrationStart AS registration_start,RegistrationEnd AS registration_end,
          StartsAt AS starts_at,EndsAt AS ends_at,IsActive AS is_active
          FROM dbo.Events WITH (UPDLOCK,HOLDLOCK) WHERE EventId=:id"""),{"id":event_id}).mappings().first()
        if old is None:raise HTTPException(404,"Evento no encontrado.")
        row=db.execute(text("""UPDATE dbo.Events SET Name=:name,EditionYear=:edition_year,
          Description=:description,Venue=:venue,RegistrationStart=:registration_start,
          RegistrationEnd=:registration_end,StartsAt=:starts_at,EndsAt=:ends_at,
          IsActive=CASE WHEN CompetitionStatus IN ('FINISHED','CANCELLED') THEN 0 ELSE IsActive END
          OUTPUT INSERTED.EventId AS id,INSERTED.Name AS name,INSERTED.EditionYear AS edition_year,
          INSERTED.CompetitionStatus AS status WHERE EventId=:id"""),values).mappings().first()
        new_data={k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in values.items() if k!='id'}
        old_data={k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in dict(old).items()}
        db.execute(text("""INSERT dbo.EventManagementAudit(EventId,ActorUserId,ActionCode,PreviousDataJson,NewDataJson)
          VALUES(:id,:actor,'UPDATED',:previous,:current)"""),
          {"id":event_id,"actor":user["user_id"],"previous":json.dumps(old_data,ensure_ascii=False),
           "current":json.dumps(new_data,ensure_ascii=False)})
        db.commit();return dict(row)
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Ya existe un evento con ese nombre y edición.")


@router.patch("/admin/events/{event_id}/status")
def transition_event(event_id:int,payload:EventStatusInput,user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    try:
        event=db.execute(text("""SELECT e.CompetitionStatus AS status,e.RegistrationStart AS registration_start,
          e.RegistrationEnd AS registration_end,COALESCE(cfg.IsEnabled,CAST(1 AS bit)) AS registration_enabled
          FROM dbo.Events e WITH (UPDLOCK,HOLDLOCK)
          LEFT JOIN dbo.EventRegistrationConfigs cfg ON cfg.EventId=e.EventId
          WHERE e.EventId=:id"""),{"id":event_id}).mappings().first()
        if event is None: raise HTTPException(404,"Evento no encontrado.")
        old=event["status"]
        if payload.status==old: return {"event_id":event_id,"status":old}
        if payload.status not in TRANSITIONS.get(old,set()):
            raise HTTPException(409,f"Transición no permitida: {old} → {payload.status}.")
        if payload.status=="SCHEDULED":
            if not event["registration_enabled"]:
                raise HTTPException(409,"Habilita las inscripciones antes de programar el evento.")
            registration_already_closed=db.execute(text("""SELECT CAST(CASE WHEN :end_date IS NOT NULL
              AND :end_date<CONVERT(date,GETDATE()) THEN 1 ELSE 0 END AS bit)"""),
              {"end_date":event["registration_end"]}).scalar_one()
            if registration_already_closed:
                raise HTTPException(409,"La fecha de cierre de inscripciones ya pasó. Actualízala antes de programar.")
            configured=db.execute(text("""SELECT TOP (1) 1
              FROM dbo.Events e
              JOIN dbo.EventCategories ec ON ec.EventId=e.EventId
              JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId AND c.IsActive=1
              JOIN dbo.Tariffs t ON t.EventId=ec.EventId AND t.CategoryId=ec.CategoryId AND t.IsActive=1
              WHERE e.EventId=:id AND ec.EventId=e.EventId AND ec.IsActive=1
                AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
                AND (e.RegistrationStart IS NULL OR t.ValidUntil IS NULL
                     OR t.ValidUntil>=e.RegistrationStart)
                AND (e.RegistrationEnd IS NULL OR t.ValidFrom<=e.RegistrationEnd)
              """), {"id":event_id}).first()
            if configured is None:
                raise HTTPException(409,"Antes de programar, asocia una categoría activa y configura una tarifa vigente para el periodo de inscripción.")
        db.execute(text("UPDATE dbo.Events SET CompetitionStatus=:status,IsActive=CASE WHEN :status IN ('FINISHED','CANCELLED') THEN 0 WHEN :status='SCHEDULED' THEN 1 ELSE IsActive END WHERE EventId=:id"),
                   {"id":event_id,"status":payload.status})
        db.execute(text("""INSERT dbo.CompetitionEventStatusHistory(EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
          VALUES(:id,:old,:new,:actor,:reason)"""),
          {"id":event_id,"old":old,"new":payload.status,"actor":user["user_id"],"reason":payload.reason})
        db.execute(text("INSERT dbo.EventStatusHistory(EventId,PreviousStatus,NewStatus,Reason,ActorUserId) VALUES(:id,:old,:new,:reason,:actor)"),
                   {"id":event_id,"old":old,"new":payload.status,"reason":payload.reason,"actor":user["user_id"]})
        db.commit();return {"event_id":event_id,"previous_status":old,"status":payload.status}
    except HTTPException:
        db.rollback();raise


def current_form(db,event_id):
    row=db.execute(text("""SELECT TOP (1) FormVersionId AS id,VersionNumber AS version,Title AS title,
       Description AS description,FieldsJson AS fields,CreatedAt AS created_at
       FROM dbo.EventFormVersions WHERE EventId=:id AND IsCurrent=1"""),{"id":event_id}).mappings().first()
    if not row:return None
    result=dict(row);result["fields"]=json.loads(result["fields"]);return result


@router.get("/events/{event_id}/form")
def get_public_form(event_id:int,db:Session=Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id AND IsActive=1"),{"id":event_id}).first() is None:
        raise HTTPException(404,"Evento no encontrado.")
    return current_form(db,event_id) or {"id":None,"version":None,"title":"Inscripción al evento","description":None,"fields":[]}


@router.put("/admin/events/{event_id}/form")
def save_form(event_id:int,payload:EventFormInput,user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"),{"id":event_id}).first() is None:
        raise HTTPException(404,"Evento no encontrado.")
    fields=[x.model_dump() for x in payload.fields]
    if not payload.title.strip():
        raise HTTPException(422,"El título del formulario no puede quedar vacío.")
    ids=[x["id"] for x in fields]
    if len(ids)!=len(set(ids)):raise HTTPException(422,"Los identificadores de campos deben ser únicos.")
    for item in fields:
        if item["type"] in {"single_choice","checkboxes","dropdown"}:
            opts=[o.strip() for o in item["options"] if o.strip()]
            if len(opts)<2 or len(opts)!=len(set(v.casefold() for v in opts)):
                raise HTTPException(422,"Cada campo de opciones necesita al menos dos opciones únicas.")
            item["options"]=opts
        else:item["options"]=[]
        item["label"]=item["label"].strip()
        if not item["label"]:
            raise HTTPException(422,"Las etiquetas del formulario no pueden quedar vacías.")
    try:
        db.execute(text("UPDATE dbo.EventFormVersions SET IsCurrent=0 WHERE EventId=:event AND IsCurrent=1"),{"event":event_id})
        version=int(db.execute(text("SELECT ISNULL(MAX(VersionNumber),0)+1 FROM dbo.EventFormVersions WHERE EventId=:event"),{"event":event_id}).scalar_one())
        row=db.execute(text("""INSERT dbo.EventFormVersions(EventId,VersionNumber,Title,Description,FieldsJson,CreatedByUserId)
          OUTPUT INSERTED.FormVersionId AS id,INSERTED.VersionNumber AS version,INSERTED.Title AS title,
          INSERTED.Description AS description,INSERTED.CreatedAt AS created_at
          VALUES(:event,:version,:title,:description,:fields,:actor)"""),
          {"event":event_id,"version":version,"title":payload.title.strip(),"description":payload.description,
           "fields":json.dumps(fields,ensure_ascii=False),"actor":user["user_id"]}).mappings().one()
        db.commit();return {**dict(row),"fields":fields}
    except Exception:
        db.rollback();raise


@router.get("/admin/events/{event_id}/form/history")
def form_history(event_id:int,page:int=Query(1,ge=1),limit:int=Query(50,ge=1,le=100),
                 _user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    total=int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.EventFormVersions WHERE EventId=:id"),{"id":event_id}).scalar_one())
    rows=db.execute(text("""SELECT FormVersionId AS id,VersionNumber AS version,Title AS title,
      Description AS description,IsCurrent AS is_current,CreatedAt AS created_at
      FROM dbo.EventFormVersions WHERE EventId=:id ORDER BY VersionNumber DESC
      OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"""),{"id":event_id,"offset":(page-1)*limit,"limit":limit}).mappings().all()
    return {"items":[dict(x) for x in rows],"page":page,"page_size":limit,"total":total,"total_pages":(total+limit-1)//limit}


@router.get("/admin/events/{event_id}/audit")
def event_audit(event_id:int,page:int=Query(1,ge=1),limit:int=Query(50,ge=1,le=100),
                _user=Depends(require_roles("ADMIN")),db:Session=Depends(get_db)):
    total=int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.EventManagementAudit WHERE EventId=:id"),{"id":event_id}).scalar_one())
    rows=db.execute(text("""SELECT AuditId AS id,ActorUserId AS actor_user_id,ActionCode AS action,
      PreviousDataJson AS previous_data,NewDataJson AS new_data,ChangedAt AS changed_at
      FROM dbo.EventManagementAudit WHERE EventId=:id ORDER BY ChangedAt DESC,AuditId DESC
      OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"""),{"id":event_id,"offset":(page-1)*limit,"limit":limit}).mappings().all()
    result=[]
    for row in rows:
        item=dict(row);item["previous_data"]=json.loads(item["previous_data"]) if item["previous_data"] else None
        item["new_data"]=json.loads(item["new_data"]);result.append(item)
    return {"items":result,"page":page,"page_size":limit,"total":total,"total_pages":(total+limit-1)//limit}
