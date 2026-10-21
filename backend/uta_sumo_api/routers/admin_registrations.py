from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text, email_lookup_hash, payment_reference_lookup_hash
from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from database import get_db

router = APIRouter(prefix="/api/v1/admin/registrations", tags=["Inscripciones administrativas"])


@router.get("")
def list_admin_registrations(
    response: Response,
    event_id: int | None = Query(None, ge=1),
    status: str | None = Query(None, min_length=1, max_length=30),
    payment_status: str | None = Query(None, pattern="^(PENDING|IN_REVIEW|PAID|REJECTED)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    participant_email: EmailStr | None = None,
    participant_id: int | None = Query(None, ge=1),
    payment_reference: str | None = Query(None, min_length=1, max_length=150),
    registration_code: str | None = Query(None, min_length=36, max_length=36),
    page: int = Query(1, ge=1, le=1_000_000),
    limit: int = Query(50, ge=1, le=100),
    _user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """Paginated administrative review list; sensitive lookups use keyed hashes."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date debe ser anterior o igual a to_date.")
    predicates, params = [], {"offset": (page - 1) * limit, "limit": limit}
    if event_id is not None:
        predicates.append("r.EventId=:event_id")
        params["event_id"] = event_id
    if status:
        predicates.append("rs.Code=:registration_status")
        params["registration_status"] = status
    if payment_status:
        predicates.append("p.PaymentStatus=:payment_status")
        params["payment_status"] = payment_status
    if from_date:
        predicates.append("r.RegisteredAt>=:from_date")
        params["from_date"] = from_date
    if to_date:
        predicates.append("r.RegisteredAt<:to_exclusive")
        params["to_exclusive"] = to_date + timedelta(days=1)
    if participant_email:
        predicates.append("u.EmailLookupHash=:participant_email_hash")
        params["participant_email_hash"] = email_lookup_hash(str(participant_email))
    if participant_id is not None:
        predicates.append("EXISTS(SELECT 1 FROM dbo.RegistrationParticipants rp WHERE rp.RegistrationId=r.RegistrationId AND rp.ParticipantId=:participant_id)")
        params["participant_id"] = participant_id
    if payment_reference:
        ref_hash = payment_reference_lookup_hash(payment_reference)
        # Legacy rows predating this index remain available by registration id/detail,
        # while newly submitted transfer references support exact safe lookup.
        predicates.append("p.PaymentReferenceLookupHash=:reference_hash")
        params["reference_hash"] = ref_hash
    if registration_code:
        predicates.append("CONVERT(varchar(36),r.RegistrationCode)=:registration_code")
        params["registration_code"] = registration_code.lower()
    where = "WHERE " + " AND ".join(predicates) if predicates else ""
    total = int(db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses rs ON rs.StatusId=r.StatusId
        LEFT JOIN dbo.Users u ON u.UserId=r.CreatedByUserId
        LEFT JOIN dbo.Payments p ON p.RegistrationId=r.RegistrationId {where}
    """), params).scalar_one())
    rows = db.execute(text(f"""
        SELECT r.RegistrationId AS id,CONVERT(varchar(36),r.RegistrationCode) AS code,
          r.RegisteredAt AS registered_at,e.EventId AS event_id,e.Name AS event_name,
          c.CategoryId AS category_id,c.Name AS category_name,
          t.TeamId AS team_id,t.Name AS team_name,b.RobotId AS robot_id,b.Name AS robot_name,
          u.EmailCiphertext AS participant_email_ciphertext,
          rs.Code AS registration_status,p.PaymentId AS payment_id,p.PaymentStatus AS payment_status,
          p.Amount AS amount,p.CurrencyCode AS currency,p.PaymentReference AS payment_reference_ciphertext,
          p.VerifiedAt AS payment_verified_at,p.VerifiedByUserId AS payment_verified_by,
          (SELECT TOP (1) h.Comments FROM dbo.StatusHistory h
             WHERE h.RegistrationId=r.RegistrationId ORDER BY h.ChangedAt DESC,h.HistoryId DESC) AS latest_review_comments
        FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses rs ON rs.StatusId=r.StatusId
        JOIN dbo.Events e ON e.EventId=r.EventId JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId JOIN dbo.Robots b ON b.RobotId=r.RobotId
        LEFT JOIN dbo.Users u ON u.UserId=r.CreatedByUserId
        LEFT JOIN dbo.Payments p ON p.RegistrationId=r.RegistrationId
        {where}
        ORDER BY r.RegisteredAt DESC,r.RegistrationId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    items = []
    for row in rows:
        item = dict(row)
        for encrypted, public in (("team_name", "team_name"), ("robot_name", "robot_name"),
                                  ("participant_email_ciphertext", "participant_email"),
                                  ("payment_reference_ciphertext", "payment_reference"),
                                  ("latest_review_comments", "latest_review_comments")):
            item[public] = decrypt_text(item.pop(encrypted))
        items.append(item)
    return {"items": items, "page": page, "page_size": limit, "total": total,
            "total_pages": (total + limit - 1) // limit}
