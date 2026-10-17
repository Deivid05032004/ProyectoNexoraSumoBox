from fastapi import APIRouter, Depends, HTTPException, Query, Response
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.crypto import decrypt_text, encrypt_text
from app.core.pagination import apply_pagination_headers

from app.dependencies.auth import get_current_user, require_roles
from app.schemas.registration import RegistrationCreate, RegistrationReview, RegistrationUpdate
from app.services.registration_service import change_registration_status
from database import get_db

router = APIRouter(prefix="/api/v1/registrations", tags=["Inscripciones"])


def _detail(db: Session, registration_id: int):
    row = db.execute(text("""
        SELECT r.RegistrationId AS id, CONVERT(varchar(36),r.RegistrationCode) AS code,
          r.RegisteredAt AS registered_at, r.Notes AS notes,
          r.CreatedByUserId AS created_by_user_id,
          e.EventId AS event_id, e.Name AS event_name, e.EditionYear AS edition_year,
          c.CategoryId AS category_id, c.Name AS category_name,
          t.TeamId AS team_id, t.Name AS team_name,
          b.RobotId AS robot_id, b.Name AS robot_name,
          s.Code AS status, s.Name AS status_name,
          p.PaymentId AS payment_id, p.PaymentStatus AS payment_status,
          p.Amount AS amount, p.PaymentReference AS payment_reference,
          p.TariffId AS tariff_id
        FROM dbo.Registrations r
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId
        JOIN dbo.Robots b ON b.RobotId=r.RobotId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        LEFT JOIN dbo.Payments p ON p.RegistrationId=r.RegistrationId
        WHERE r.RegistrationId=:id
    """), {"id": registration_id}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["notes"] = decrypt_text(result["notes"])
    result["team_name"] = decrypt_text(result["team_name"])
    result["robot_name"] = decrypt_text(result["robot_name"])
    result["payment_reference"] = decrypt_text(result["payment_reference"])
    result["participants"] = [dict(r) for r in db.execute(text("""
        SELECT p.ParticipantId AS id, p.FirstName AS first_name, p.LastName AS last_name,
          rp.Role AS role, p.InstitutionId AS institution_id
        FROM dbo.RegistrationParticipants rp
        JOIN dbo.Participants p ON p.ParticipantId=rp.ParticipantId
        WHERE rp.RegistrationId=:id ORDER BY p.ParticipantId
    """), {"id": registration_id}).mappings().all()]
    for participant in result["participants"]:
        participant["first_name"] = decrypt_text(participant["first_name"])
        participant["last_name"] = decrypt_text(participant["last_name"])
    return result


def _authorized_registration(db, registration_id, user, *, reviewer=True):
    detail = _detail(db, registration_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    if user["role"] == "PARTICIPANT" and detail["created_by_user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    if user["role"] == "TREASURY" and detail["status"] != "PAYMENT_REVIEW":
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    return detail


@router.post("", status_code=201)
def create_registration(payload: RegistrationCreate,
                        user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    participant_ids = [p.participant_id for p in payload.participants]
    if len(set(participant_ids)) != len(participant_ids):
        raise HTTPException(status_code=422, detail="No repita participantes en la inscripción.")
    if sum(p.role == "PARTICIPANT" for p in payload.participants) < 1:
        raise HTTPException(status_code=422, detail="La inscripción requiere al menos un participante.")

    profile = db.execute(text("SELECT InstitutionId FROM dbo.Participants WHERE UserId=:id"),
                         {"id": user["user_id"]}).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=409, detail="La cuenta no tiene perfil de participante.")
    team = db.execute(text("SELECT InstitutionId FROM dbo.Teams WHERE TeamId=:id AND OwnerUserId=:owner"),
                      {"id": payload.team_id, "owner": user["user_id"]}).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    if team != profile:
        raise HTTPException(status_code=422, detail="El equipo debe corresponder a la institución del perfil.")
    robot = db.execute(text("SELECT 1 FROM dbo.Robots WHERE RobotId=:id AND OwnerUserId=:owner"),
                       {"id": payload.robot_id, "owner": user["user_id"]}).first()
    if robot is None:
        raise HTTPException(status_code=404, detail="Robot no encontrado.")

    # Bind an expanding parameter to keep participant IDs parameterized.
    from sqlalchemy import bindparam
    owned_count = db.execute(text("""
        SELECT COUNT(*) FROM dbo.Participants
        WHERE UserId=:owner AND ParticipantId IN :ids
    """).bindparams(bindparam("ids", expanding=True)),
        {"owner": user["user_id"], "ids": participant_ids}).scalar_one()
    if owned_count != len(participant_ids):
        raise HTTPException(status_code=403, detail="Solo puede asociar participantes vinculados a su cuenta.")

    valid = db.execute(text("""
        SELECT e.EventId, t.TariffId, t.Amount
        FROM dbo.Events e JOIN dbo.Categories c ON c.CategoryId=:category AND c.IsActive=1
        JOIN dbo.Tariffs t ON t.EventId=e.EventId AND t.CategoryId=c.CategoryId
        WHERE e.EventId=:event AND e.IsActive=1
          AND (e.RegistrationStart IS NULL OR e.RegistrationStart<=CONVERT(date,GETDATE()))
          AND (e.RegistrationEnd IS NULL OR e.RegistrationEnd>=CONVERT(date,GETDATE()))
          AND t.IsActive=1 AND t.ValidFrom<=CONVERT(date,GETDATE())
          AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
    """), {"event": payload.event_id, "category": payload.category_id}).mappings().first()
    if valid is None:
        raise HTTPException(status_code=422, detail="Evento/categoría/tarifa no disponible para inscripción.")

    initial_status = db.execute(text("SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='PAYMENT_PENDING'")).scalar_one_or_none()
    if initial_status is None:
        raise HTTPException(status_code=503, detail="Falta el estado PAYMENT_PENDING en la base de datos.")
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Registrations (EventId,CategoryId,TeamId,RobotId,StatusId,Notes,CreatedByUserId)
            OUTPUT INSERTED.RegistrationId AS id, CONVERT(varchar(36),INSERTED.RegistrationCode) AS code
            VALUES (:event,:category,:team,:robot,:status,:notes,:owner)
        """), {"event": payload.event_id, "category": payload.category_id,
              "team": payload.team_id, "robot": payload.robot_id,
              "status": initial_status, "notes": encrypt_text(payload.notes),
              "owner": user["user_id"]}).mappings().one()
        registration_id = row["id"]
        for item in payload.participants:
            db.execute(text("""
                INSERT INTO dbo.RegistrationParticipants (RegistrationId,ParticipantId,Role)
                VALUES (:registration,:participant,:role)
            """), {"registration": registration_id, "participant": item.participant_id,
                  "role": item.role})
        db.execute(text("""
            INSERT INTO dbo.Payments (RegistrationId,TariffId,Amount,PaymentStatus)
            VALUES (:registration,:tariff,:amount,'PENDING')
        """), {"registration": registration_id, "tariff": valid["TariffId"],
              "amount": valid["Amount"]})
        db.execute(text("""
            INSERT INTO dbo.StatusHistory (RegistrationId,PreviousStatusId,NewStatusId,ChangedByUserId,Comments)
            VALUES (:registration,NULL,:status,:actor,:comments)
        """), {"registration": registration_id, "status": initial_status,
              "actor": user["user_id"], "comments": encrypt_text("Inscripción creada")})
        db.commit()
        return _detail(db, registration_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe esa combinación de equipo, robot, categoría y evento.")
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="No se pudo completar la inscripción; no se guardaron cambios parciales.")


@router.get("")
def list_registrations(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                       status: str | None = None, event_id: int | None = None,
                       user=Depends(get_current_user), db: Session = Depends(get_db)):
    clauses, params = [], {"offset": (page-1)*limit, "limit": limit}
    if user["role"] == "PARTICIPANT":
        clauses.append("r.CreatedByUserId=:owner")
        params["owner"] = user["user_id"]
    elif user["role"] == "TREASURY":
        clauses.append("s.Code='PAYMENT_REVIEW'")
    if status:
        clauses.append("s.Code=:status")
        params["status"] = status
    if event_id:
        clauses.append("r.EventId=:event_id")
        params["event_id"] = event_id
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    total = db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId {where}
    """), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT r.RegistrationId AS id, CONVERT(varchar(36),r.RegistrationCode) AS code,
          r.RegisteredAt AS registered_at, e.Name AS event_name, e.EditionYear AS edition_year,
          c.Name AS category_name, t.Name AS team_name, b.Name AS robot_name, s.Code AS status
        FROM dbo.Registrations r JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId JOIN dbo.Robots b ON b.RobotId=r.RobotId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        {where} ORDER BY r.RegisteredAt DESC,r.RegistrationId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = [dict(r) for r in rows]
    for row in result:
        row["team_name"] = decrypt_text(row["team_name"])
        row["robot_name"] = decrypt_text(row["robot_name"])
    return result


@router.get("/{registration_id}")
def get_registration(registration_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _authorized_registration(db, registration_id, user)
    return _detail(db, registration_id)


@router.get("/code/{registration_code}")
def get_registration_by_code(registration_code: UUID, user=Depends(get_current_user),
                             db: Session = Depends(get_db)):
    registration_id = db.execute(text("""
        SELECT RegistrationId FROM dbo.Registrations WHERE RegistrationCode=:code
    """), {"code": str(registration_code)}).scalar_one_or_none()
    if registration_id is None:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    _authorized_registration(db, registration_id, user)
    return _detail(db, registration_id)


@router.get("/{registration_id}/history")
def registration_history(registration_id: int, response: Response,
                         page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                         user=Depends(get_current_user), db: Session = Depends(get_db)):
    _authorized_registration(db, registration_id, user)
    total = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.StatusHistory WHERE RegistrationId=:id"),
                       {"id": registration_id}).scalar_one()
    rows = db.execute(text("""
        SELECT old.Code AS previous_status, new.Code AS new_status,
          h.Comments AS comments, h.ChangedAt AS changed_at,
          u.EmailCiphertext AS changed_by
        FROM dbo.StatusHistory h
        LEFT JOIN dbo.RegistrationStatuses old ON old.StatusId=h.PreviousStatusId
        JOIN dbo.RegistrationStatuses new ON new.StatusId=h.NewStatusId
        LEFT JOIN dbo.Users u ON u.UserId=h.ChangedByUserId
        WHERE h.RegistrationId=:id ORDER BY h.ChangedAt, h.HistoryId
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"id": registration_id, "offset": (page - 1) * limit,
           "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = [dict(r) for r in rows]
    for row in result:
        row["comments"] = decrypt_text(row["comments"])
        row["changed_by"] = decrypt_text(row["changed_by"])
    return result


@router.patch("/{registration_id}")
def update_registration(registration_id: int, payload: RegistrationUpdate,
                        user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    record = _authorized_registration(db, registration_id, user)
    if record["status"] not in ("PAYMENT_PENDING", "OBSERVED"):
        raise HTTPException(status_code=409, detail="La inscripción ya no admite cambios del usuario.")
    db.execute(text("UPDATE dbo.Registrations SET Notes=:notes WHERE RegistrationId=:id"),
               {"id": registration_id, "notes": encrypt_text(payload.notes)})
    db.commit()
    return _detail(db, registration_id)


@router.post("/{registration_id}/cancel")
def cancel_registration(registration_id: int, user=Depends(require_roles("PARTICIPANT")),
                        db: Session = Depends(get_db)):
    record = _authorized_registration(db, registration_id, user)
    if record["status"] not in ("PAYMENT_PENDING", "OBSERVED"):
        raise HTTPException(status_code=409, detail="La inscripción ya no se puede cancelar.")
    change_registration_status(db, registration_id, "CANCELLED", user["user_id"], "Cancelada por participante")
    db.commit()
    return _detail(db, registration_id)


@router.post("/{registration_id}/review")
def review_registration(registration_id: int, payload: RegistrationReview,
                        user=Depends(require_roles("ADMIN", "REVIEWER")), db: Session = Depends(get_db)):
    record = _detail(db, registration_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    allowed = {
        "PENDING": {"APPROVED", "OBSERVED", "REJECTED"},
        "OBSERVED": {"APPROVED", "REJECTED"},
    }
    if payload.status not in allowed.get(record["status"], set()):
        raise HTTPException(status_code=409, detail=f"Transición inválida desde {record['status']}.")
    change_registration_status(db, registration_id, payload.status, user["user_id"], payload.comments)
    db.commit()
    return _detail(db, registration_id)
