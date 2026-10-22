from pathlib import Path
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import MAX_RECEIPT_BYTES, RECEIPT_STORAGE_DIR
from app.core.crypto import (decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text,
                             payment_reference_lookup_hash)
from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import get_current_user, require_roles
from app.schemas.payment import PaymentReview
from app.services.registration_service import change_registration_status
from app.services.registration_delivery import deliver_outbox
from database import get_db

router = APIRouter(prefix="/api/v1/payments", tags=["Pagos"])

_FORMATS = {
    ".pdf": ("application/pdf", lambda b: b.startswith(b"%PDF-")),
    ".jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ".png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n") and len(b) >= 24 and b[12:16] == b"IHDR"),
}


def _payment(db: Session, payment_id: int):
    row = db.execute(text("""
        SELECT p.PaymentId AS id, p.RegistrationId AS registration_id,
          p.TariffId AS tariff_id, p.Amount AS amount,p.CurrencyCode AS currency, p.PaymentStatus AS status,
          p.PaymentReference AS payment_reference, p.VerifiedByUserId AS verified_by_user_id,
          p.VerifiedAt AS verified_at, r.CreatedByUserId AS owner_user_id,
          s.Code AS registration_status,
          (SELECT TOP (1) h.Comments FROM dbo.StatusHistory h
             WHERE h.RegistrationId=r.RegistrationId ORDER BY h.ChangedAt DESC,h.HistoryId DESC) AS review_comments,
          pr.StorageKey AS receipt_key, pr.MediaType AS receipt_media_type,
          pr.UploadedAt AS receipt_uploaded_at, pr.EncryptionVersion AS receipt_encryption_version
        FROM dbo.Payments p JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        LEFT JOIN dbo.PaymentReceipts pr ON pr.PaymentId=p.PaymentId AND pr.IsCurrent=1
        WHERE p.PaymentId=:id
    """), {"id": payment_id}).mappings().first()
    if not row:
        return None
    result = dict(row)
    result["payment_reference"] = decrypt_text(result["payment_reference"])
    result["review_comments"] = decrypt_text(result["review_comments"])
    return result


def _authorize(payment, user):
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if user["role"] == "PARTICIPANT" and payment["owner_user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if user["role"] not in ("PARTICIPANT", "ADMIN"):
        raise HTTPException(status_code=403, detail="No tiene permiso para consultar pagos.")


@router.get("")
def list_payments(response: Response, status: str | None = None, page: int = Query(1, ge=1, le=1_000_000),
                  limit: int = Query(50, ge=1, le=100),
                  user=Depends(get_current_user), db: Session = Depends(get_db)):
    return _list_payments(response, status, page, limit, user, db)


@router.get("/my")
def my_payments(response: Response,
                status: str | None = Query(default=None, pattern="^(PENDING|IN_REVIEW|PAID|REJECTED)$"),
                page: int = Query(1, ge=1, le=1_000_000),
                limit: int = Query(50, ge=1, le=100),
                user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    """Return the authenticated participant's existing payment orders."""
    return _list_payments(response, status, page, limit, user, db)


def _list_payments(response: Response, status: str | None, page: int, limit: int,
                   user, db: Session):
    if user["role"] not in ("ADMIN", "PARTICIPANT"):
        raise HTTPException(status_code=403, detail="No tiene permiso para consultar pagos.")
    clauses, params = [], {"offset": (page-1)*limit, "limit": limit}
    if user["role"] == "PARTICIPANT":
        clauses.append("r.CreatedByUserId=:owner")
        params["owner"] = user["user_id"]
    if status:
        clauses.append("p.PaymentStatus=:status")
        params["status"] = status
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    total = db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Payments p
        JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId {where}
    """), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT p.PaymentId AS id, p.RegistrationId AS registration_id,
          CONVERT(varchar(36),r.RegistrationCode) AS registration_code,
          p.Amount AS amount,p.CurrencyCode AS currency, p.PaymentStatus AS status, p.PaymentReference AS payment_reference,
          p.CreatedAt AS created_at, r.RegisteredAt AS registration_created_at,
          s.Code AS registration_status, r.EventId AS event_id, e.Name AS event_name,
          (SELECT TOP (1) h.Comments FROM dbo.StatusHistory h
             WHERE h.RegistrationId=r.RegistrationId ORDER BY h.ChangedAt DESC,h.HistoryId DESC) AS review_comments,
          r.CategoryId AS category_id, c.Name AS category_name,
          t.TeamId AS team_id, t.Name AS team_name, b.RobotId AS robot_id,
          b.Name AS robot_name, pr.UploadedAt AS receipt_uploaded_at,
          CASE WHEN pr.ReceiptId IS NULL THEN CAST(0 AS bit) ELSE CAST(1 AS bit) END AS has_receipt
        FROM dbo.Payments p JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId
        JOIN dbo.Robots b ON b.RobotId=r.RobotId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        LEFT JOIN dbo.PaymentReceipts pr ON pr.PaymentId=p.PaymentId AND pr.IsCurrent=1
        {where} ORDER BY p.CreatedAt DESC,p.PaymentId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = [dict(r) for r in rows]
    for row in result:
        row["payment_reference"] = decrypt_text(row["payment_reference"])
        row["review_comments"] = decrypt_text(row["review_comments"])
        row["team_name"] = decrypt_text(row["team_name"])
        row["robot_name"] = decrypt_text(row["robot_name"])
        row["can_upload_receipt"] = (
            row["status"] in ("PENDING", "REJECTED")
            and row["registration_status"] == "PAYMENT_PENDING"
        )
    return result


@router.get("/{payment_id}")
def get_payment(payment_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    payment = _payment(db, payment_id)
    _authorize(payment, user)
    payment["has_receipt"] = bool(payment.get("receipt_key"))
    payment["can_upload_receipt"] = (
        payment["status"] in ("PENDING", "REJECTED")
        and payment["registration_status"] == "PAYMENT_PENDING"
    )
    payment.pop("owner_user_id", None)
    payment.pop("receipt_key", None)
    return payment


@router.post("/{payment_id}/receipt", status_code=202)
async def submit_receipt(payment_id: int, file: UploadFile = File(...),
                         payment_reference: str | None = Form(default=None, max_length=150),
                         user=Depends(require_roles("PARTICIPANT")),
                         db: Session = Depends(get_db)):
    payment = _payment(db, payment_id)
    _authorize(payment, user)
    if payment["status"] not in ("PENDING", "REJECTED"):
        raise HTTPException(status_code=409, detail="El pago ya fue enviado a revisión o verificado.")
    if payment["registration_status"] != "PAYMENT_PENDING":
        raise HTTPException(status_code=409, detail="La inscripción no admite presentar comprobantes en su estado actual.")
    extension = Path(file.filename or "").suffix.lower()
    expected = _FORMATS.get(extension)
    if expected is None or file.content_type != expected[0]:
        raise HTTPException(status_code=415, detail="Solo se aceptan PDF, JPEG o PNG válidos.")
    content = await file.read(MAX_RECEIPT_BYTES + 1)
    if len(content) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="El comprobante supera el tamaño máximo permitido.")
    if not content or not expected[1](content):
        raise HTTPException(status_code=415, detail="El contenido no coincide con el tipo de archivo declarado.")

    key = f"{uuid4().hex}{extension}"
    RECEIPT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = RECEIPT_STORAGE_DIR / key
    staging = RECEIPT_STORAGE_DIR / f".{key}.tmp"
    try:
        with staging.open("xb") as output:
            output.write(encrypt_bytes(content))
            output.flush()
            os.fsync(output.fileno())
        # Publish the complete file atomically before committing its metadata.
        os.replace(staging, target)
        # Keep previous receipts as historical evidence; only one version is current.
        db.execute(text("UPDATE dbo.PaymentReceipts SET IsCurrent=0 WHERE PaymentId=:id AND IsCurrent=1"),
                   {"id": payment_id})
        db.execute(text("""
            INSERT INTO dbo.PaymentReceipts (PaymentId,StorageKey,MediaType,UploadedByUserId,IsCurrent,EncryptionVersion)
            VALUES (:payment,:key,:type,:user,1,1)
        """), {"payment": payment_id, "key": key, "type": expected[0], "user": user["user_id"]})
        db.execute(text("""
            UPDATE dbo.Payments SET PaymentStatus='IN_REVIEW', PaymentReference=:reference,
              PaymentReferenceLookupHash=:reference_hash,
              VerifiedByUserId=NULL, VerifiedAt=NULL
            WHERE PaymentId=:id
        """), {"id": payment_id, "reference": encrypt_text(payment_reference),
              "reference_hash": payment_reference_lookup_hash(payment_reference)})
        registration_id = payment["registration_id"]
        change_registration_status(db, registration_id, "PAYMENT_REVIEW", user["user_id"],
                                  "Comprobante presentado; pendiente de revisión de tesorería")
        # Queue an encrypted confirmation in the same transaction as the receipt
        # and state change. The uploaded bank document is deliberately not emailed.
        notification = db.execute(text("""
            SELECT u.EmailCiphertext,u.FirstName,e.Name AS event_name,
                   CONVERT(varchar(36),r.RegistrationCode) AS registration_code
            FROM dbo.Registrations r
            JOIN dbo.Users u ON u.UserId=r.CreatedByUserId
            JOIN dbo.Events e ON e.EventId=r.EventId
            WHERE r.RegistrationId=:registration
        """), {"registration": registration_id}).mappings().one()
        participant_name = decrypt_text(notification["FirstName"])
        event_name = notification["event_name"]
        message_type = f"PAYMENT_PROOF_{uuid4().hex[:23]}"
        outbox_id = db.execute(text("""
            INSERT INTO dbo.EmailOutbox(RegistrationId,MessageType,RecipientCiphertext,Subject,BodyText)
            OUTPUT INSERTED.OutboxId
            VALUES(:registration,:message_type,:recipient,:subject,:body)
        """), {
            "registration": registration_id,
            "message_type": message_type,
            "recipient": notification["EmailCiphertext"],
            "subject": encrypt_text(f"Comprobante recibido — {event_name}"),
            "body": encrypt_text(
                f"Hola {participant_name},\n\n"
                f"Recibimos el comprobante de pago de tu inscripción "
                f"{notification['registration_code']} para {event_name}.\n"
                "El pago quedó pendiente de revisión administrativa. Te notificaremos "
                "cuando sea aprobado o si necesitas corregir el comprobante.\n"
            ),
        }).scalar_one()
        db.commit()
    except Exception:
        db.rollback()
        staging.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    try:
        notification_status = deliver_outbox(db, outbox_id)
    except SQLAlchemyError:
        db.rollback()
        notification_status = "PENDING"
    return {"payment_id": payment_id, "status": "IN_REVIEW", "receipt_uploaded": True,
            "notification_status": notification_status}


@router.get("/{payment_id}/receipt")
def download_receipt(payment_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    payment = _payment(db, payment_id)
    _authorize(payment, user)
    key = payment.get("receipt_key")
    if not key:
        raise HTTPException(status_code=404, detail="El pago no tiene comprobante.")
    # StorageKey is generated by the server; resolve and enforce storage-root containment.
    root = RECEIPT_STORAGE_DIR.resolve()
    path = (root / key).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Comprobante no disponible.")
    try:
        content = path.read_bytes()
        if payment.get("receipt_encryption_version") == 1:
            content = decrypt_bytes(content)
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="No se pudo descifrar el comprobante almacenado.")
    return Response(content=content, media_type=payment["receipt_media_type"],
                    headers={"Content-Disposition": f'attachment; filename="comprobante-{payment_id}{path.suffix}"',
                             "Cache-Control": "no-store"})


@router.post("/{payment_id}/review")
def review_payment(payment_id: int, payload: PaymentReview,
                   user=Depends(require_roles("ADMIN")),
                   db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT p.PaymentStatus,p.RegistrationId,s.Code,e.Name AS event_name,
          p.Amount,p.CurrencyCode,u.EmailCiphertext,u.FirstName
        FROM dbo.Payments p WITH (UPDLOCK, ROWLOCK)
        JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Users u ON u.UserId=r.CreatedByUserId
        WHERE p.PaymentId=:id
    """), {"id": payment_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if row[0] != "IN_REVIEW":
        raise HTTPException(status_code=409, detail="Solo se revisan pagos con comprobante pendiente.")
    if row[2] != "PAYMENT_REVIEW":
        raise HTTPException(status_code=409, detail="El estado de inscripción no coincide con la revisión de pago.")
    if payload.status == "REJECTED" and not (payload.comments and payload.comments.strip()):
        raise HTTPException(status_code=422, detail="Indique el motivo del rechazo.")
    registration_id = row[1]
    target_registration_status = "PENDING" if payload.status == "PAID" else "PAYMENT_PENDING"
    try:
        result = db.execute(text("""
            UPDATE dbo.Payments SET PaymentStatus=:status, VerifiedByUserId=:actor,
              VerifiedAt=SYSDATETIME()
            WHERE PaymentId=:id AND PaymentStatus='IN_REVIEW'
        """), {"id": payment_id, "status": payload.status,
              "actor": user["user_id"]})
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="El pago cambió durante la revisión.")
        change_registration_status(db, registration_id, target_registration_status,
                                  user["user_id"], payload.comments)
        from app.core.crypto import decrypt_text
        recipient = decrypt_text(row[6])
        participant_name = decrypt_text(row[7])
        if payload.status == "PAID":
            subject = f"Pago aprobado — {row[3]}"
            body = f"Hola {participant_name},\n\nEl pago de tu inscripción para {row[3]} fue aprobado.\n"
            message_type = "PAYMENT_APPROVED"
        else:
            subject = f"Comprobante de pago rechazado — {row[3]}"
            body = (f"Hola {participant_name},\n\nEl comprobante de pago para {row[3]} requiere corrección.\n"
                    f"Motivo: {payload.comments.strip()}\nPuedes cargar un nuevo comprobante desde la plataforma.\n")
            message_type = f"PAYMENT_REJECTED_{uuid4().hex[:23]}"
        outbox_id = db.execute(text("""
            INSERT INTO dbo.EmailOutbox(RegistrationId,MessageType,RecipientCiphertext,Subject,BodyText)
            OUTPUT INSERTED.OutboxId
            VALUES(:registration,:message_type,:recipient,:subject,:body)
        """), {"registration": registration_id, "message_type": message_type,
              "recipient": encrypt_text(recipient), "subject": encrypt_text(subject),
              "body": encrypt_text(body)}).scalar_one()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="No se pudo registrar la revisión del pago.")
    payment = _payment(db, payment_id)
    try:
        payment["notification_status"] = deliver_outbox(db, outbox_id)
    except SQLAlchemyError:
        db.rollback()
        payment["notification_status"] = "PENDING"
    payment.pop("owner_user_id", None)
    payment.pop("receipt_key", None)
    return payment
