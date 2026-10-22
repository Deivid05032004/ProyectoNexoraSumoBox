from fastapi import APIRouter, Depends, HTTPException, Query, Response
from uuid import UUID
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.crypto import decrypt_text, encrypt_text
from app.core.pagination import apply_pagination_headers
from app.core.config import RECEIPT_STORAGE_DIR
from app.core.crypto import decrypt_bytes

from app.dependencies.auth import get_current_user, require_roles
from app.schemas.registration import RegistrationCreate, RegistrationReview, RegistrationUpdate
from app.services.registration_service import change_registration_status
from app.services.registration_delivery import (build_payment_instruction_pdf, deliver_outbox,
                                                receipt_path, store_pdf)
from database import get_db

router = APIRouter(prefix="/api/v1/registrations", tags=["Inscripciones"])


def _detail(db: Session, registration_id: int, *, viewer_role: str | None = None):
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
          p.TariffId AS tariff_id, p.CreatedAt AS payment_created_at,
          pr.UploadedAt AS receipt_uploaded_at,
          CASE WHEN pr.ReceiptId IS NULL THEN CAST(0 AS bit) ELSE CAST(1 AS bit) END AS has_receipt
        FROM dbo.Registrations r
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId
        JOIN dbo.Robots b ON b.RobotId=r.RobotId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        LEFT JOIN dbo.Payments p ON p.RegistrationId=r.RegistrationId
        LEFT JOIN dbo.PaymentReceipts pr ON pr.PaymentId=p.PaymentId AND pr.IsCurrent=1
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
          rp.Role AS role, rp.RegistrationPosition AS position,
          p.InstitutionId AS institution_id, i.Name AS institution_name,
          p.MobilePhone AS mobile_phone
        FROM dbo.RegistrationParticipants rp
        JOIN dbo.Participants p ON p.ParticipantId=rp.ParticipantId
        JOIN dbo.Institutions i ON i.InstitutionId=p.InstitutionId
        WHERE rp.RegistrationId=:id
        ORDER BY rp.RegistrationPosition, CASE rp.Role WHEN 'PARTICIPANT' THEN 1 ELSE 2 END,
                 p.ParticipantId
    """), {"id": registration_id}).mappings().all()]
    for participant in result["participants"]:
        participant["first_name"] = decrypt_text(participant["first_name"])
        participant["last_name"] = decrypt_text(participant["last_name"])
        participant["mobile_phone"] = decrypt_text(participant["mobile_phone"])
        if participant["position"] is not None:
            participant["slot"] = {1: "PARTICIPANT_1", 2: "PARTICIPANT_2", 3: "COACH"}.get(
                participant["position"], "UNASSIGNED")
        else:
            participant["slot"] = None
        if viewer_role == "EVENT_MANAGER":
            participant["mobile_phone"] = None
    if viewer_role == "EVENT_MANAGER":
        result["payment_reference"] = None
    result["can_upload_receipt"] = (
        result["payment_status"] in ("PENDING", "REJECTED")
        and result["status"] == "PAYMENT_PENDING"
    ) if result.get("payment_id") is not None else False
    return result


def _authorized_registration(db, registration_id, user):
    detail = _detail(db, registration_id, viewer_role=user["role"])
    if detail is None:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    if user["role"] == "PARTICIPANT" and detail["created_by_user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    detail.pop("created_by_user_id", None)
    return detail


@router.post("", status_code=201)
def create_registration(payload: RegistrationCreate,
                        user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    participant_ids = [p.participant_id for p in payload.participants if p.participant_id is not None]
    if len(set(participant_ids)) != len(participant_ids):
        raise HTTPException(status_code=422, detail="No repita participantes en la inscripción.")
    team = db.execute(text("SELECT InstitutionId FROM dbo.Teams WHERE TeamId=:id AND OwnerUserId=:owner"),
                      {"id": payload.team_id, "owner": user["user_id"]}).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    if db.execute(text("SELECT 1 FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1"),
                  {"id": team}).first() is None:
        raise HTTPException(status_code=422, detail="La institución del equipo no existe o está inactiva.")
    robot = db.execute(text("SELECT 1 FROM dbo.Robots WHERE RobotId=:id AND OwnerUserId=:owner"),
                       {"id": payload.robot_id, "owner": user["user_id"]}).first()
    if robot is None:
        raise HTTPException(status_code=404, detail="Robot no encontrado.")

    # Bind an expanding parameter to keep participant IDs parameterized.
    from sqlalchemy import bindparam
    if participant_ids:
        owned_count = db.execute(text("""
            SELECT COUNT(*) FROM dbo.Participants
            WHERE UserId=:owner AND ParticipantId IN :ids
        """).bindparams(bindparam("ids", expanding=True)),
            {"owner": user["user_id"], "ids": participant_ids}).scalar_one()
        if owned_count != len(participant_ids):
            raise HTTPException(status_code=403, detail="Solo puede asociar participantes vinculados explícitamente a su cuenta.")

    valid = db.execute(text("""
        SELECT TOP (1) e.EventId,e.Name AS EventName,c.Name AS CategoryName,t.TariffId,t.Amount,
          ec.MinParticipants,ec.MaxParticipants,ec.MinCoaches,ec.MaxCoaches,ec.MaxRegistrations,
          cfg.IsEnabled AS RegistrationEnabled,cfg.OrganizationName,cfg.FormInstructions,
          cfg.PaymentInstructions,cfg.PaymentMethodsJson,cfg.ContactEmail,cfg.ContactPhone,
          cfg.ReceiptMessage,cfg.Currency,cfg.FormTitle
        FROM dbo.Events e JOIN dbo.Categories c ON c.CategoryId=:category AND c.IsActive=1
        JOIN dbo.EventCategories ec WITH (UPDLOCK,HOLDLOCK)
          ON ec.EventId=e.EventId AND ec.CategoryId=c.CategoryId AND ec.IsActive=1
        JOIN dbo.Tariffs t ON t.EventId=e.EventId AND t.CategoryId=c.CategoryId
        LEFT JOIN dbo.EventRegistrationConfigs cfg ON cfg.EventId=e.EventId
        WHERE e.EventId=:event AND e.IsActive=1
          AND (e.RegistrationStart IS NULL OR e.RegistrationStart<=CONVERT(date,GETDATE()))
          AND (e.RegistrationEnd IS NULL OR e.RegistrationEnd>=CONVERT(date,GETDATE()))
          AND t.IsActive=1 AND t.ValidFrom<=CONVERT(date,GETDATE())
          AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
        ORDER BY t.ValidFrom DESC, t.TariffId DESC
    """), {"event": payload.event_id, "category": payload.category_id}).mappings().first()
    if valid is None:
        raise HTTPException(status_code=422, detail="Evento/categoría/tarifa no disponible para inscripción.")
    if valid["RegistrationEnabled"] is False:
        raise HTTPException(status_code=409, detail="Las inscripciones de este evento están deshabilitadas.")
    participant_count = sum(person.role == "PARTICIPANT" for person in payload.participants)
    coach_count = sum(person.role == "COACH" for person in payload.participants)
    if not valid["MinParticipants"] <= participant_count <= valid["MaxParticipants"]:
        raise HTTPException(status_code=422, detail=(
            f"La categoría requiere entre {valid['MinParticipants']} y "
            f"{valid['MaxParticipants']} participantes."
        ))
    if not valid["MinCoaches"] <= coach_count <= valid["MaxCoaches"]:
        raise HTTPException(status_code=422, detail=(
            f"La categoría permite entre {valid['MinCoaches']} y {valid['MaxCoaches']} coaches."
        ))
    if valid["MaxRegistrations"] is not None:
        registrations_count = db.execute(text("""
            SELECT COUNT_BIG(*) FROM dbo.Registrations WITH (UPDLOCK,HOLDLOCK)
            WHERE EventId=:event AND CategoryId=:category
        """), {"event": payload.event_id, "category": payload.category_id}).scalar_one()
        if registrations_count >= valid["MaxRegistrations"]:
            raise HTTPException(status_code=409, detail="La categoría alcanzó su cupo de inscripciones.")

    initial_status = db.execute(text("SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='PAYMENT_PENDING'")).scalar_one_or_none()
    if initial_status is None:
        raise HTTPException(status_code=503, detail="Falta el estado PAYMENT_PENDING en la base de datos.")
    generated_document_path = None
    committed = False
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
        for position, item in enumerate(payload.participants, start=1):
            if item.participant_id is None:
                institution_active = db.execute(text("""
                    SELECT 1 FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1
                """), {"id": item.institution_id}).first()
                if institution_active is None:
                    raise HTTPException(status_code=422, detail="La institución de un integrante no existe o está inactiva.")
                participant_id = db.execute(text("""
                    INSERT INTO dbo.Participants (FirstName,LastName,MobilePhone,InstitutionId,UserId)
                    OUTPUT INSERTED.ParticipantId
                    VALUES (:first,:last,:phone,:institution,NULL)
                """), {"first": encrypt_text(item.first_name.strip()),
                      "last": encrypt_text(item.last_name.strip()),
                      "phone": encrypt_text(item.mobile_phone),
                      "institution": item.institution_id}).scalar_one()
            else:
                participant_id = item.participant_id
            db.execute(text("""
                INSERT INTO dbo.RegistrationParticipants
                    (RegistrationId,ParticipantId,Role,RegistrationPosition)
                VALUES (:registration,:participant,:role,:position)
            """), {"registration": registration_id, "participant": participant_id,
                  "role": item.role, "position": position})
        db.execute(text("""
            INSERT INTO dbo.Payments (RegistrationId,TariffId,Amount,CurrencyCode,PaymentStatus)
            VALUES (:registration,:tariff,:amount,:currency,'PENDING')
        """), {"registration": registration_id, "tariff": valid["TariffId"],
              "amount": valid["Amount"], "currency": valid["Currency"] or "USD"})
        db.execute(text("""
            INSERT INTO dbo.StatusHistory (RegistrationId,PreviousStatusId,NewStatusId,ChangedByUserId,Comments)
            VALUES (:registration,NULL,:status,:actor,:comments)
        """), {"registration": registration_id, "status": initial_status,
              "actor": user["user_id"], "comments": encrypt_text("Inscripción creada")})
        identity = db.execute(text("""
            SELECT EmailCiphertext,FirstName,LastName FROM dbo.Users WHERE UserId=:id
        """), {"id": user["user_id"]}).mappings().one()
        email = decrypt_text(identity["EmailCiphertext"])
        first_name = decrypt_text(identity["FirstName"])
        last_name = decrypt_text(identity["LastName"])
        payment_methods = decrypt_text(valid["PaymentMethodsJson"])
        import json
        payment_methods = json.loads(payment_methods) if payment_methods else []
        from datetime import datetime, timezone
        pdf = build_payment_instruction_pdf({
            "organization_name": valid["OrganizationName"] or "UTA SUMO ROBOTICS CUP",
            "form_title": valid["FormTitle"], "form_instructions": decrypt_text(valid["FormInstructions"]),
            "event_name": valid["EventName"], "registration_code": row["code"],
            "participant_name": f"{first_name} {last_name}".strip(), "email": email,
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "category_name": db.execute(text("SELECT Name FROM dbo.Categories WHERE CategoryId=:id"),
                                         {"id": payload.category_id}).scalar_one(),
            "currency": valid["Currency"] or "USD", "amount": valid["Amount"],
            "payment_instructions": decrypt_text(valid["PaymentInstructions"]),
            "payment_methods": payment_methods, "receipt_message": decrypt_text(valid["ReceiptMessage"]),
            "contact_email": valid["ContactEmail"], "contact_phone": decrypt_text(valid["ContactPhone"]),
        })
        key, digest = store_pdf(registration_id, pdf)
        generated_document_path = RECEIPT_STORAGE_DIR / key
        document_id = db.execute(text("""
            INSERT INTO dbo.RegistrationDocuments(RegistrationId,DocumentType,StorageKey,MediaType,Sha256)
            OUTPUT INSERTED.DocumentId
            VALUES(:registration,'PAYMENT_INSTRUCTION',:key,'application/pdf',:sha)
        """), {"registration": registration_id, "key": key, "sha": digest}).scalar_one()
        body = (f"Hola {first_name},\n\nTu inscripción {row['code']} para {valid['EventName']} fue creada. "
                f"El valor pendiente es {valid['Currency'] or 'USD'} {valid['Amount']:.2f}. "
                "Adjuntamos el documento con las instrucciones de pago. Después de transferir, carga el comprobante "
                "en la plataforma; el pago quedará pendiente hasta su revisión administrativa.\n")
        outbox_id = db.execute(text("""
            INSERT INTO dbo.EmailOutbox(RegistrationId,DocumentId,MessageType,RecipientCiphertext,Subject,BodyText)
            OUTPUT INSERTED.OutboxId
            VALUES(:registration,:document,'REGISTRATION_PAYMENT_REQUEST',:recipient,:subject,:body)
        """), {"registration": registration_id, "document": document_id,
              "recipient": encrypt_text(email),
              "subject": encrypt_text(f"Inscripción {valid['EventName']} — instrucciones de pago"),
              "body": encrypt_text(body)}).scalar_one()
        db.commit()
        committed = True
        try:
            email_delivery_status = deliver_outbox(db, outbox_id)
        except SQLAlchemyError:
            # Registration and outbox are durable; a worker/admin retry can deliver later.
            db.rollback()
            email_delivery_status = "PENDING"
        result = _detail(db, registration_id, viewer_role="PARTICIPANT")
        result.pop("created_by_user_id", None)
        result["receipt_url"] = f"/api/v1/registrations/{registration_id}/receipt"
        result["email_delivery_status"] = email_delivery_status
        return result
    except HTTPException:
        db.rollback()
        if not committed and generated_document_path:
            generated_document_path.unlink(missing_ok=True)
        raise
    except IntegrityError:
        db.rollback()
        if not committed and generated_document_path:
            generated_document_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Ya existe esa combinación de equipo, robot, categoría y evento.")
    except SQLAlchemyError:
        db.rollback()
        if not committed and generated_document_path:
            generated_document_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="No se pudo completar la inscripción; no se guardaron cambios parciales.")
    except Exception:
        db.rollback()
        if not committed and generated_document_path:
            generated_document_path.unlink(missing_ok=True)
        raise


@router.get("")
def list_registrations(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                       status: str | None = None, event_id: int | None = None,
                       user=Depends(get_current_user), db: Session = Depends(get_db)):
    clauses, params = [], {"offset": (page-1)*limit, "limit": limit}
    if user["role"] == "PARTICIPANT":
        clauses.append("r.CreatedByUserId=:owner")
        params["owner"] = user["user_id"]
    elif user["role"] == "ADMIN":
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


@router.get("/my")
def my_registrations(response: Response,
                     page: int = Query(1, ge=1, le=1_000_000),
                     limit: int = Query(50, ge=1, le=100),
                     status: str | None = None, event_id: int | None = None,
                     user=Depends(require_roles("PARTICIPANT")),
                     db: Session = Depends(get_db)):
    """Return the authenticated participant's persisted registrations and orders."""
    clauses = ["r.CreatedByUserId=:owner"]
    params = {"owner": user["user_id"], "offset": (page - 1) * limit, "limit": limit}
    if status:
        clauses.append("s.Code=:status")
        params["status"] = status
    if event_id is not None:
        clauses.append("r.EventId=:event_id")
        params["event_id"] = event_id
    where = " AND ".join(clauses)
    total = db.execute(text(f"""
        SELECT COUNT_BIG(*) FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        WHERE {where}
    """), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT r.RegistrationId AS id, CONVERT(varchar(36),r.RegistrationCode) AS code,
          r.EventId AS event_id, e.Name AS event_name, e.EditionYear AS edition_year,
          r.CategoryId AS category_id, c.Name AS category_name,
          r.TeamId AS team_id, t.Name AS team_name,
          r.RobotId AS robot_id, b.Name AS robot_name,
          r.RegisteredAt AS registered_at, s.Code AS status, s.Name AS status_name,
          p.PaymentId AS payment_id, p.Amount AS amount, p.PaymentStatus AS payment_status,
          p.CreatedAt AS payment_created_at,
          pr.UploadedAt AS receipt_uploaded_at,
          CASE WHEN pr.ReceiptId IS NULL THEN CAST(0 AS bit) ELSE CAST(1 AS bit) END AS has_receipt
        FROM dbo.Registrations r
        JOIN dbo.Events e ON e.EventId=r.EventId
        JOIN dbo.Categories c ON c.CategoryId=r.CategoryId
        JOIN dbo.Teams t ON t.TeamId=r.TeamId
        JOIN dbo.Robots b ON b.RobotId=r.RobotId
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
        LEFT JOIN dbo.Payments p ON p.RegistrationId=r.RegistrationId
        LEFT JOIN dbo.PaymentReceipts pr ON pr.PaymentId=p.PaymentId AND pr.IsCurrent=1
        WHERE {where}
        ORDER BY r.RegisteredAt DESC,r.RegistrationId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), params).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = [dict(row) for row in rows]
    if not result:
        return result

    registration_ids = [row["id"] for row in result]
    roster_rows = db.execute(text("""
        SELECT rp.RegistrationId AS registration_id, p.ParticipantId AS id,
          p.FirstName AS first_name, p.LastName AS last_name, rp.Role AS role,
          rp.RegistrationPosition AS position, p.InstitutionId AS institution_id,
          i.Name AS institution_name, p.MobilePhone AS mobile_phone
        FROM dbo.RegistrationParticipants rp
        JOIN dbo.Participants p ON p.ParticipantId=rp.ParticipantId
        JOIN dbo.Institutions i ON i.InstitutionId=p.InstitutionId
        WHERE rp.RegistrationId IN :registration_ids
        ORDER BY rp.RegistrationId, rp.RegistrationPosition,
                 CASE rp.Role WHEN 'PARTICIPANT' THEN 1 ELSE 2 END, p.ParticipantId
    """).bindparams(bindparam("registration_ids", expanding=True)),
        {"registration_ids": registration_ids}).mappings().all()
    rosters = {registration_id: [] for registration_id in registration_ids}
    for item in roster_rows:
        person = dict(item)
        registration_id = person.pop("registration_id")
        for field in ("first_name", "last_name", "mobile_phone"):
            person[field] = decrypt_text(person[field])
        position = person["position"]
        person["slot"] = {1: "PARTICIPANT_1", 2: "PARTICIPANT_2", 3: "COACH"}.get(position)
        rosters[registration_id].append(person)

    for row in result:
        row["team_name"] = decrypt_text(row["team_name"])
        row["robot_name"] = decrypt_text(row["robot_name"])
        row["participants"] = rosters[row["id"]]
        row["can_upload_receipt"] = (
            row["payment_status"] in ("PENDING", "REJECTED")
            and row["status"] == "PAYMENT_PENDING"
        ) if row["payment_id"] is not None else False
    return result


@router.get("/{registration_id}")
def get_registration(registration_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return _authorized_registration(db, registration_id, user)


@router.get("/{registration_id}/receipt")
def download_registration_receipt(registration_id: int, user=Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    if user["role"] not in ("PARTICIPANT", "ADMIN"):
        raise HTTPException(status_code=403, detail="No tiene permiso para descargar el comprobante.")
    _authorized_registration(db, registration_id, user)
    document = db.execute(text("""
        SELECT TOP (1) StorageKey FROM dbo.RegistrationDocuments
        WHERE RegistrationId=:id AND DocumentType='PAYMENT_INSTRUCTION'
        ORDER BY CreatedAt DESC,DocumentId DESC
    """), {"id": registration_id}).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="El comprobante de solicitud no está disponible.")
    path = receipt_path(document)
    if path is None:
        raise HTTPException(status_code=404, detail="El comprobante de solicitud no está disponible.")
    try:
        content = decrypt_bytes(path.read_bytes())
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="No se pudo leer el comprobante almacenado.")
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="inscripcion-{registration_id}-pago.pdf"',
        "Cache-Control": "no-store",
    })


@router.get("/code/{registration_code}")
def get_registration_by_code(registration_code: UUID, user=Depends(get_current_user),
                             db: Session = Depends(get_db)):
    registration_id = db.execute(text("""
        SELECT RegistrationId FROM dbo.Registrations WHERE RegistrationCode=:code
    """), {"code": str(registration_code)}).scalar_one_or_none()
    if registration_id is None:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")
    return _authorized_registration(db, registration_id, user)


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
          h.ChangedByUserId AS changed_by_user_id,u.EmailCiphertext AS changed_by
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
        if user["role"] == "ADMIN":
            row["changed_by"] = decrypt_text(row["changed_by"])
        else:
            row.pop("changed_by_user_id", None)
            row["changed_by"] = None
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
    result = _detail(db, registration_id, viewer_role="PARTICIPANT")
    result.pop("created_by_user_id", None)
    return result


@router.post("/{registration_id}/cancel")
def cancel_registration(registration_id: int, user=Depends(require_roles("PARTICIPANT")),
                        db: Session = Depends(get_db)):
    record = _authorized_registration(db, registration_id, user)
    if record["status"] not in ("PAYMENT_PENDING", "OBSERVED"):
        raise HTTPException(status_code=409, detail="La inscripción ya no se puede cancelar.")
    change_registration_status(db, registration_id, "CANCELLED", user["user_id"], "Cancelada por participante")
    db.commit()
    result = _detail(db, registration_id, viewer_role="PARTICIPANT")
    result.pop("created_by_user_id", None)
    return result


@router.post("/{registration_id}/review")
def review_registration(registration_id: int, payload: RegistrationReview,
                        user=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
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
    result = _detail(db, registration_id, viewer_role="ADMIN")
    result.pop("created_by_user_id", None)
    return result
