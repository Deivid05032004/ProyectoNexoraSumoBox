from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from app.services.registration_delivery import deliver_outbox
from database import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["Administración de correo"])


@router.get("/email-outbox")
def list_email_outbox(response: Response, status: str | None = Query(None, pattern="^(PENDING|SENT|FAILED)$"),
                      page: int = Query(1, ge=1, le=1_000_000),
                      limit: int = Query(50, ge=1, le=100),
                      _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    where = "WHERE DeliveryStatus=:status" if status else ""
    params = {"status": status, "offset": (page-1)*limit, "limit": limit}
    total = int(db.execute(text(f"SELECT COUNT_BIG(*) FROM dbo.EmailOutbox {where}"), params).scalar_one())
    rows = db.execute(text(f"""
        SELECT OutboxId AS id,RegistrationId AS registration_id,MessageType AS message_type,
          DeliveryStatus AS status,Attempts AS attempts,LastError AS last_error,
          CreatedAt AS created_at,SentAt AS sent_at
        FROM dbo.EmailOutbox {where}
        ORDER BY CreatedAt DESC,OutboxId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    return [dict(row) for row in rows]


@router.post("/email-outbox/{outbox_id}/retry")
def retry_email(outbox_id: int, _user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    row = db.execute(text("SELECT DeliveryStatus,Attempts FROM dbo.EmailOutbox WHERE OutboxId=:id"),
                     {"id": outbox_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")
    if row[0] == "SENT":
        raise HTTPException(status_code=409, detail="El correo ya fue enviado; use reenvío para crear otro intento.")
    if row[1] >= 10:
        raise HTTPException(status_code=409, detail="Se alcanzó el límite de 10 intentos; revise la configuración SMTP.")
    status = deliver_outbox(db, outbox_id)
    return {"outbox_id": outbox_id, "status": status}


@router.post("/registrations/{registration_id}/resend-receipt", status_code=202)
def resend_payment_instruction(registration_id: int, _user=Depends(require_roles("ADMIN")),
                               db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT TOP (1) o.RecipientCiphertext,o.Subject,o.BodyText,o.DocumentId
        FROM dbo.EmailOutbox o WHERE o.RegistrationId=:id
        ORDER BY o.CreatedAt DESC,o.OutboxId DESC
    """), {"id": registration_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No existe una notificación de inscripción para reenviar.")
    outbox_id = db.execute(text("""
        INSERT INTO dbo.EmailOutbox(RegistrationId,DocumentId,MessageType,RecipientCiphertext,Subject,BodyText)
        OUTPUT INSERTED.OutboxId
        VALUES(:registration,:document,CONCAT('RESEND_',REPLACE(CONVERT(varchar(36),NEWID()),'-','')),
          :recipient,:subject,:body)
    """), {"registration": registration_id, "document": row["DocumentId"],
          "recipient": row["RecipientCiphertext"], "subject": row["Subject"], "body": row["BodyText"]}).scalar_one()
    db.commit()
    status = deliver_outbox(db, outbox_id)
    return {"outbox_id": outbox_id, "status": status}
