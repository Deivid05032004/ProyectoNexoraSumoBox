"""Aggregate, privacy-conscious tournament reports for dashboards and exports."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from database import get_db

router = APIRouter(prefix="/api/v1/reports", tags=["Reportes"])


def _page_result(items, total: int, page: int, limit: int):
    return {"items": [dict(row) for row in items], "page": page, "page_size": limit,
            "total": total, "total_pages": (total + limit - 1) // limit}


def _event_exists(db: Session, event_id: int | None) -> None:
    if event_id is not None and not db.execute(
        text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}
    ).first():
        raise HTTPException(status_code=404, detail="Evento no encontrado.")


@router.get("/overview")
def overview(
    event_id: int | None = Query(None, ge=1),
    user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
    db: Session = Depends(get_db),
):
    """Role-aware KPI cards. Financial totals are visible only to ADMIN."""
    _event_exists(db, event_id)
    registrations = db.execute(text("""
        SELECT COUNT_BIG(*) AS total,
          SUM(CASE WHEN s.Code='APPROVED' THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS approved,
          SUM(CASE WHEN s.Code='PENDING' THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS awaiting_review,
          SUM(CASE WHEN s.Code IN ('REJECTED','CANCELLED') THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS closed
        FROM dbo.Registrations r JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        WHERE (:event_id IS NULL OR r.EventId=:event_id)
    """), {"event_id": event_id}).mappings().one()
    result = {
        "event_id": event_id,
        "registrations": {key: int(registrations[key] or 0) for key in ("total", "approved", "awaiting_review", "closed")},
    }
    if user["role"] == "ADMIN":
        payments = db.execute(text("""
            SELECT COUNT_BIG(*) AS total,
              SUM(CASE WHEN p.PaymentStatus IN ('PENDING','IN_REVIEW') THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS pending_review,
              SUM(CASE WHEN p.PaymentStatus='PAID' THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS paid
            FROM dbo.Payments p JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
            WHERE (:event_id IS NULL OR r.EventId=:event_id)
        """), {"event_id": event_id}).mappings().one()
        result["payments"] = {key: int(payments[key] or 0) for key in ("total", "pending_review", "paid")}
    if user["role"] == "ADMIN":
        result["active_users"] = int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Users WHERE IsActive=1")).scalar_one())
    return result


@router.get("/registrations/by-status")
def registrations_by_status(
    event_id: int | None = Query(None, ge=1),
    user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
    db: Session = Depends(get_db),
):
    _event_exists(db, event_id)
    rows = db.execute(text("""
        SELECT s.Code AS status, s.Name AS label, COUNT_BIG(r.RegistrationId) AS count
        FROM dbo.RegistrationStatuses s
        LEFT JOIN dbo.Registrations r ON r.StatusId=s.StatusId
          AND (:event_id IS NULL OR r.EventId=:event_id)
        GROUP BY s.Code,s.Name,s.StatusId ORDER BY s.StatusId
    """), {"event_id": event_id}).mappings().all()
    return {"event_id": event_id, "items": [{**dict(row), "count": int(row["count"])} for row in rows]}


@router.get("/registrations/by-category")
def registrations_by_category(
    event_id: int | None = Query(None, ge=1),
    user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
    db: Session = Depends(get_db),
):
    _event_exists(db, event_id)
    rows = db.execute(text("""
        SELECT c.CategoryId AS category_id,c.Name AS category,
          COUNT_BIG(r.RegistrationId) AS registrations,
          SUM(CASE WHEN s.Code='APPROVED' THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS approved
        FROM dbo.Categories c
        LEFT JOIN dbo.Registrations r ON r.CategoryId=c.CategoryId
          AND (:event_id IS NULL OR r.EventId=:event_id)
        LEFT JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        WHERE c.IsActive=1 OR r.RegistrationId IS NOT NULL
        GROUP BY c.CategoryId,c.Name ORDER BY c.Name
    """), {"event_id": event_id}).mappings().all()
    return {"event_id": event_id, "items": [
        {**dict(row), "registrations": int(row["registrations"]), "approved": int(row["approved"] or 0)}
        for row in rows
    ]}


@router.get("/registrations/trend")
def registration_trend(
    event_id: int | None = Query(None, ge=1),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
    db: Session = Depends(get_db),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date debe ser anterior o igual a to_date.")
    _event_exists(db, event_id)
    rows = db.execute(text("""
        SELECT DATEFROMPARTS(YEAR(r.RegisteredAt),MONTH(r.RegisteredAt),1) AS month,
          COUNT_BIG(*) AS registrations,
          SUM(CASE WHEN s.Code='APPROVED' THEN CONVERT(BIGINT,1) ELSE CONVERT(BIGINT,0) END) AS approved
        FROM dbo.Registrations r JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        WHERE (:event_id IS NULL OR r.EventId=:event_id)
          AND (:from_date IS NULL OR r.RegisteredAt>=:from_date)
          AND (:to_date IS NULL OR r.RegisteredAt<DATEADD(day,1,:to_date))
        GROUP BY DATEFROMPARTS(YEAR(r.RegisteredAt),MONTH(r.RegisteredAt),1)
        ORDER BY month
    """), {"event_id": event_id, "from_date": from_date, "to_date": to_date}).mappings().all()
    return {"event_id": event_id, "from_date": from_date, "to_date": to_date,
            "items": [{**dict(row), "registrations": int(row["registrations"]),
                       "approved": int(row["approved"] or 0)} for row in rows]}


@router.get("/payments/summary")
def payment_summary(
    event_id: int | None = Query(None, ge=1),
    user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    _event_exists(db, event_id)
    rows = db.execute(text("""
        SELECT p.PaymentStatus AS status,p.CurrencyCode AS currency,COUNT_BIG(*) AS count,
          SUM(p.Amount) AS amount
        FROM dbo.Payments p JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
        WHERE (:event_id IS NULL OR r.EventId=:event_id)
        GROUP BY p.PaymentStatus,p.CurrencyCode ORDER BY p.PaymentStatus,p.CurrencyCode
    """), {"event_id": event_id}).mappings().all()
    items = [{"status": row["status"], "currency": row["currency"], "count": int(row["count"]), "amount": row["amount"] or 0}
             for row in rows]
    currencies = {item["currency"] for item in items}
    return {"event_id": event_id, "items": items,
            "total_count": sum(item["count"] for item in items),
            # Kept for older clients; null when adding different currencies would be misleading.
            "total_amount": sum((item["amount"] for item in items), start=0) if len(currencies) <= 1 else None,
            "totals_by_currency": {currency: sum((item["amount"] for item in items if item["currency"] == currency), start=0)
                                   for currency in sorted(currencies)}}


@router.get("/registrations/details")
def registration_details(
    event_id: int | None = Query(None, ge=1),
    status: str | None = Query(None, min_length=1, max_length=30),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    page: int = Query(1, ge=1, le=1_000_000),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
    db: Session = Depends(get_db),
):
    """Paginated operational rows; participant identity and free text are omitted."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date debe ser anterior o igual a to_date.")
    _event_exists(db, event_id)
    predicates, params = [], {"offset": (page - 1) * limit, "limit": limit}
    if event_id is not None:
        predicates.append("r.EventId=:event_id")
        params["event_id"] = event_id
    if status is not None:
        predicates.append("s.Code=:status")
        params["status"] = status
    if from_date is not None:
        predicates.append("r.RegisteredAt>=:from_date")
        params["from_date"] = from_date
    if to_date is not None:
        predicates.append("r.RegisteredAt<DATEADD(day,1,:to_date)")
        params["to_date"] = to_date
    where = "WHERE " + " AND ".join(predicates) if predicates else ""
    total = int(db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId {where}
    """), params).scalar_one())
    rows = db.execute(text(f"""
        SELECT r.RegistrationId AS registration_id,
          CONVERT(varchar(36),r.RegistrationCode) AS registration_code,
          r.EventId AS event_id,e.Name AS event_name,r.CategoryId AS category_id,
          c.Name AS category,s.Code AS status,r.RegisteredAt AS registered_at
        FROM dbo.Registrations r
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        {where}
        ORDER BY r.RegisteredAt DESC,r.RegistrationId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    return {"event_id": event_id, "status": status, "from_date": from_date,
            "to_date": to_date, **_page_result(rows, total, page, limit)}


@router.get("/payments/details")
def payment_details(
    event_id: int | None = Query(None, ge=1),
    status: str | None = Query(None, min_length=1, max_length=20),
    page: int = Query(1, ge=1, le=1_000_000),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """Paginated financial rows without exposing payment reference or PII."""
    _event_exists(db, event_id)
    predicates, params = [], {"offset": (page - 1) * limit, "limit": limit}
    if event_id is not None:
        predicates.append("r.EventId=:event_id")
        params["event_id"] = event_id
    if status is not None:
        predicates.append("p.PaymentStatus=:status")
        params["status"] = status
    where = "WHERE " + " AND ".join(predicates) if predicates else ""
    total = int(db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Payments p
        JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId {where}
    """), params).scalar_one())
    rows = db.execute(text(f"""
        SELECT p.PaymentId AS payment_id,p.RegistrationId AS registration_id,
          r.EventId AS event_id,p.Amount AS amount,p.CurrencyCode AS currency,p.PaymentStatus AS status,
          p.CreatedAt AS created_at,p.VerifiedAt AS verified_at
        FROM dbo.Payments p JOIN dbo.Registrations r ON r.RegistrationId=p.RegistrationId
        {where}
        ORDER BY p.CreatedAt DESC,p.PaymentId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    return {"event_id": event_id, "status": status,
            **_page_result(rows, total, page, limit)}
