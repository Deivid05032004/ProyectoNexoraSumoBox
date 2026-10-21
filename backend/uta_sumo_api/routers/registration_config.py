import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text, encrypt_text
from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from app.schemas.registration_config import RegistrationConfigUpdate
from database import get_db

router = APIRouter(tags=["Configuración de inscripción"])


def _shape(row, *, admin: bool):
    if row is None:
        return None
    item = dict(row)
    methods = decrypt_text(item.pop("payment_methods_ciphertext", None))
    item["payment_methods"] = json.loads(methods) if methods else []
    for key in ("form_description", "form_instructions", "payment_instructions",
                "contact_phone", "receipt_message"):
        item[key] = decrypt_text(item.get(key))
    if not admin:
        item.pop("updated_by_user_id", None)
        item.pop("updated_at", None)
    return item


def _get(db: Session, event_id: int):
    return db.execute(text("""
        SELECT c.EventId AS event_id,e.Name AS event_name,e.EditionYear AS edition_year,
          e.RegistrationStart AS registration_start,e.RegistrationEnd AS registration_end,
          CAST(CASE WHEN e.IsActive=1 AND c.IsEnabled=1
            AND (e.RegistrationStart IS NULL OR e.RegistrationStart<=CONVERT(date,GETDATE()))
            AND (e.RegistrationEnd IS NULL OR e.RegistrationEnd>=CONVERT(date,GETDATE()))
            THEN 1 ELSE 0 END AS bit) AS registration_open,
          c.OrganizationName AS organization_name,c.FormTitle AS form_title,
          c.FormDescription AS form_description,c.FormInstructions AS form_instructions,
          c.PaymentInstructions AS payment_instructions,
          c.PaymentMethodsJson AS payment_methods_ciphertext,c.ContactEmail AS contact_email,
          c.ContactPhone AS contact_phone,c.ReceiptMessage AS receipt_message,
          c.Currency AS currency,c.IsEnabled AS is_enabled,
          c.UpdatedByUserId AS updated_by_user_id,c.UpdatedAt AS updated_at
        FROM dbo.EventRegistrationConfigs c JOIN dbo.Events e ON e.EventId=c.EventId
        WHERE c.EventId=:id
    """), {"id": event_id}).mappings().first()


@router.get("/api/v1/events/{event_id}/registration-config")
def public_registration_config(event_id: int, db: Session = Depends(get_db)):
    active_event = db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id AND IsActive=1"),
                              {"id": event_id}).first()
    if active_event is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    row = _get(db, event_id)
    if row is None:
        event = db.execute(text("""
            SELECT EventId AS event_id,Name AS event_name,EditionYear AS edition_year,
              RegistrationStart AS registration_start,RegistrationEnd AS registration_end,
              CAST(CASE WHEN (RegistrationStart IS NULL OR RegistrationStart<=CONVERT(date,GETDATE()))
                AND (RegistrationEnd IS NULL OR RegistrationEnd>=CONVERT(date,GETDATE()))
                THEN 1 ELSE 0 END AS bit) AS registration_open
            FROM dbo.Events WHERE EventId=:id AND IsActive=1
        """), {"id": event_id}).mappings().first()
        if event is None:
            raise HTTPException(status_code=404, detail="Evento no encontrado.")
        result = {**dict(event), "organization_name": "UTA SUMO ROBOTICS CUP",
                  "form_title": "Inscripción al evento", "form_description": None,
                  "form_instructions": None, "payment_instructions": None,
                  "payment_methods": [], "contact_email": None, "contact_phone": None,
                  "receipt_message": None, "currency": "USD", "is_enabled": True}
    else:
        result = _shape(row, admin=False)
    tariffs = db.execute(text("""
        WITH current_tariffs AS (
          SELECT t.TariffId,t.CategoryId,c.Name AS CategoryName,t.Amount,t.ValidFrom,t.ValidUntil,
            ROW_NUMBER() OVER(PARTITION BY t.CategoryId ORDER BY t.ValidFrom DESC,t.TariffId DESC) AS rn
          FROM dbo.Tariffs t JOIN dbo.Categories c ON c.CategoryId=t.CategoryId
          WHERE t.EventId=:event AND t.IsActive=1 AND c.IsActive=1
            AND t.ValidFrom<=CONVERT(date,GETDATE())
            AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
        )
        SELECT TariffId AS tariff_id,CategoryId AS category_id,CategoryName AS category,
          Amount AS amount,ValidFrom AS valid_from,ValidUntil AS valid_until
        FROM current_tariffs WHERE rn=1 ORDER BY CategoryName
    """), {"event": event_id}).mappings().all()
    result["tariffs"] = [dict(item) for item in tariffs]
    return result


@router.get("/api/v1/admin/events/{event_id}/registration-config")
def admin_registration_config(event_id: int, _user=Depends(require_roles("ADMIN")),
                              db: Session = Depends(get_db)):
    event_exists = db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first()
    if event_exists is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    return _shape(_get(db, event_id), admin=True) or {
        "event_id": event_id, "organization_name": "UTA SUMO ROBOTICS CUP",
        "form_title": "Inscripción al evento", "form_description": None,
        "form_instructions": None, "payment_instructions": None, "payment_methods": [],
        "contact_email": None, "contact_phone": None, "receipt_message": None,
        "currency": "USD", "is_enabled": True, "updated_by_user_id": None, "updated_at": None,
    }


@router.put("/api/v1/admin/events/{event_id}/registration-config")
def update_registration_config(event_id: int, payload: RegistrationConfigUpdate,
                               user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    values = payload.model_dump()
    new_snapshot = encrypt_text(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False))
    previous = _get(db, event_id)
    if previous:
        previous_methods = decrypt_text(previous["payment_methods_ciphertext"])
        previous_config = {key: previous.get(key) for key in (
            "organization_name", "form_title", "form_description", "form_instructions",
            "payment_instructions", "contact_email", "contact_phone", "receipt_message",
            "currency", "is_enabled")}
        previous_config["payment_methods"] = json.loads(previous_methods) if previous_methods else []
        previous_snapshot = encrypt_text(json.dumps(previous_config, ensure_ascii=False, default=str))
    else:
        previous_snapshot = None
    values["contact_email"] = str(payload.contact_email) if payload.contact_email else None
    values["payment_methods_json"] = encrypt_text(json.dumps(values.pop("payment_methods"), ensure_ascii=False))
    for field in ("form_description", "form_instructions", "payment_instructions", "contact_phone", "receipt_message"):
        values[field] = encrypt_text(values[field])
    values.update(event_id=event_id, actor=user["user_id"])
    try:
        row = db.execute(text("""
            MERGE dbo.EventRegistrationConfigs WITH (HOLDLOCK) AS target
            USING (SELECT :event_id AS EventId) AS source ON target.EventId=source.EventId
            WHEN MATCHED THEN UPDATE SET OrganizationName=:organization_name,FormTitle=:form_title,
              FormDescription=:form_description,FormInstructions=:form_instructions,
              PaymentInstructions=:payment_instructions,PaymentMethodsJson=:payment_methods_json,
              ContactEmail=:contact_email,ContactPhone=:contact_phone,ReceiptMessage=:receipt_message,
              Currency=:currency,IsEnabled=:is_enabled,UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT(EventId,OrganizationName,FormTitle,FormDescription,
              FormInstructions,PaymentInstructions,PaymentMethodsJson,ContactEmail,ContactPhone,
              ReceiptMessage,Currency,IsEnabled,UpdatedByUserId)
            VALUES(:event_id,:organization_name,:form_title,:form_description,:form_instructions,
              :payment_instructions,:payment_methods_json,:contact_email,:contact_phone,
              :receipt_message,:currency,:is_enabled,:actor)
            OUTPUT INSERTED.EventId AS event_id,INSERTED.OrganizationName AS organization_name,
              INSERTED.FormTitle AS form_title,INSERTED.FormDescription AS form_description,
              INSERTED.FormInstructions AS form_instructions,INSERTED.PaymentInstructions AS payment_instructions,
              INSERTED.PaymentMethodsJson AS payment_methods_ciphertext,INSERTED.ContactEmail AS contact_email,
              INSERTED.ContactPhone AS contact_phone,INSERTED.ReceiptMessage AS receipt_message,
              INSERTED.Currency AS currency,INSERTED.IsEnabled AS is_enabled,
              INSERTED.UpdatedByUserId AS updated_by_user_id,INSERTED.UpdatedAt AS updated_at;
        """), values).mappings().one()
        db.execute(text("""
            INSERT INTO dbo.EventRegistrationConfigAudit(EventId,ActorUserId,PreviousConfigCiphertext,NewConfigCiphertext)
            VALUES(:event,:actor,:previous,:current)
        """), {"event": event_id, "actor": user["user_id"], "previous": previous_snapshot,
              "current": new_snapshot})
        db.commit()
        return _shape(row, admin=True)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar la configuración del evento.")


@router.get("/api/v1/admin/events/{event_id}/registration-config/history")
def registration_config_history(event_id: int, response: Response,
                                 page: int = Query(1, ge=1, le=1_000_000),
                                 limit: int = Query(50, ge=1, le=100),
                                 _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    total = int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.EventRegistrationConfigAudit WHERE EventId=:id"),
                           {"id": event_id}).scalar_one())
    rows = db.execute(text("""
        SELECT AuditId AS id,ActorUserId AS actor_user_id,PreviousConfigCiphertext AS previous,
          NewConfigCiphertext AS current_config,ChangedAt AS changed_at
        FROM dbo.EventRegistrationConfigAudit WHERE EventId=:id
        ORDER BY ChangedAt DESC,AuditId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"id": event_id, "offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    result = []
    for row in rows:
        item = dict(row)
        item["previous"] = json.loads(decrypt_text(item["previous"])) if item["previous"] else None
        item["current"] = json.loads(decrypt_text(item.pop("current_config")))
        result.append(item)
    return result
