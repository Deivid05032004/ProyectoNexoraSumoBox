from fastapi import APIRouter, Depends, HTTPException, Query, Response
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import require_roles
from app.core.crypto import decrypt_text
from app.core.pagination import apply_pagination_headers
from app.schemas.resources import UserAdminUpdate
from app.schemas.resources import AdminUserCreate
from app.core.config import EMAIL_CHECK_DELIVERABILITY
from app.core.password_policy import validate_password
from app.core.security import hash_password
from app.core.crypto import email_lookup_hash, encrypt_text
from database import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["Administración"])


@router.post("/users", status_code=201)
def create_privileged_user(payload: AdminUserCreate, actor=Depends(require_roles("ADMIN")),
                           db: Session = Depends(get_db)):
    try:
        email = validate_email(payload.email, check_deliverability=EMAIL_CHECK_DELIVERABILITY,
                               timeout=5, globally_deliverable=True).normalized.casefold()
        validate_password(payload.password, email)
    except (EmailNotValidError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload.first_name.strip() or not payload.last_name.strip():
        raise HTTPException(status_code=422, detail="Nombre y apellido son obligatorios.")
    role_id = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:role"),
                         {"role": payload.role}).scalar_one_or_none()
    if role_id is None:
        raise HTTPException(status_code=422, detail="El rol indicado no existe.")
    try:
        user_id = db.execute(text("""
          INSERT dbo.Users(EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive)
          OUTPUT INSERTED.UserId
          VALUES(:email,:lookup,:password,:first,:last,:role,1)
        """), {"email":encrypt_text(email),"lookup":email_lookup_hash(email),
          "password":hash_password(payload.password),"first":encrypt_text(payload.first_name.strip()),
          "last":encrypt_text(payload.last_name.strip()),"role":role_id}).scalar_one()
        db.execute(text("""INSERT dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode,NewRoleId,NewIsActive)
          VALUES(:target,:actor,'ACCOUNT_CREATED',:role,1)"""),
          {"target":user_id,"actor":actor["user_id"],"role":role_id})
        db.commit()
        return {"id":user_id,"email":email,"role":payload.role,"is_active":True}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo.")


@router.get("/roles", dependencies=[Depends(require_roles("ADMIN"))])
def roles(db: Session = Depends(get_db)):
    return [dict(r) for r in db.execute(text("SELECT RoleId AS id, Code AS code, Name AS name FROM dbo.Roles ORDER BY Code")).mappings()]


@router.get("/users", dependencies=[Depends(require_roles("ADMIN"))])
def users(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(5, ge=1, le=100),
          db: Session = Depends(get_db)):
    total = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Users")).scalar_one()
    rows = db.execute(text("""
        SELECT u.UserId AS id, u.EmailCiphertext AS email_ciphertext, u.FirstName AS first_name,
          u.LastName AS last_name, u.IsActive AS is_active, u.CreatedAt AS created_at,
          r.Code AS role FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        ORDER BY u.UserId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = []
    for row in rows:
        item = dict(row)
        item["email"] = decrypt_text(item.pop("email_ciphertext"))
        item["username"] = item["email"]
        item["first_name"] = decrypt_text(item["first_name"])
        item["last_name"] = decrypt_text(item["last_name"])
        result.append(item)
    return result


@router.patch("/users/{user_id}", dependencies=[Depends(require_roles("ADMIN"))])
def update_user(user_id: int, payload: UserAdminUpdate,
                actor=Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if payload.is_active is None and payload.role is None:
        raise HTTPException(status_code=422, detail="Indique un rol o el estado activo.")
    target = db.execute(text("""
        SELECT u.UserId, u.IsActive, u.RoleId, r.Code FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        WHERE u.UserId=:id
    """), {"id": user_id}).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    old_active, old_role_id, old_role = target[1], target[2], target[3]
    new_active = old_active if payload.is_active is None else payload.is_active
    new_role = old_role if payload.role is None else payload.role
    demotes_self = user_id == actor["user_id"] and (not new_active or new_role != "ADMIN")
    if demotes_self:
        admins = db.execute(text("""
            SELECT COUNT(*) FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
            WHERE u.IsActive=1 AND r.Code='ADMIN'
        """)).scalar_one()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="No se puede desactivar al único administrador activo.")
    role_id = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:code"),
                         {"code": new_role}).scalar_one_or_none()
    if role_id is None:
        raise HTTPException(status_code=422, detail="Rol inexistente.")
    row = db.execute(text("""
        UPDATE dbo.Users SET IsActive=:active, RoleId=:role_id, TokenVersion=TokenVersion+1
        OUTPUT INSERTED.UserId AS id, INSERTED.EmailCiphertext AS email_ciphertext,
          INSERTED.IsActive AS is_active
        WHERE UserId=:id
    """), {"id": user_id, "active": new_active, "role_id": role_id}).mappings().one()
    db.execute(text("""
        INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode,
          PreviousRoleId,NewRoleId,PreviousIsActive,NewIsActive)
        VALUES (:target,:actor,'ACCOUNT_UPDATED',:old_role,:new_role,:old_active,:new_active)
    """), {"target": user_id, "actor": actor["user_id"], "old_role": old_role_id,
          "new_role": role_id, "old_active": old_active, "new_active": new_active})
    db.commit()
    result = dict(row)
    result["email"] = decrypt_text(result.pop("email_ciphertext"))
    result["username"] = result["email"]
    return {**result, "role": new_role}


@router.get("/dashboard", dependencies=[Depends(require_roles("ADMIN"))])
def dashboard(db: Session = Depends(get_db)):
    registrations = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Registrations")).scalar_one()
    pending_payments = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Payments WHERE PaymentStatus IN ('PENDING','IN_REVIEW')")).scalar_one()
    active_users = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Users WHERE IsActive=1")).scalar_one()
    return {"registrations": registrations, "payments_pending_review": pending_payments,
            "active_users": active_users,
            "reports_url": "/api/v1/reports/overview"}


@router.get("/audit/users", dependencies=[Depends(require_roles("ADMIN"))])
def user_security_audit(response: Response, target_user_id: int | None = Query(None, ge=1),
                        page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(5, ge=1, le=100),
                        db: Session = Depends(get_db)):
    total = db.execute(text("""
        SELECT COUNT_BIG(*) FROM dbo.UserSecurityAudit
        WHERE (:target IS NULL OR TargetUserId=:target)
    """), {"target": target_user_id}).scalar_one()
    rows = db.execute(text("""
        SELECT a.AuditId AS id,a.TargetUserId AS target_user_id,
          target.EmailCiphertext AS target_email_ciphertext,a.ActorUserId AS actor_user_id,
          actor.EmailCiphertext AS actor_email_ciphertext,a.ActionCode AS action,
          old_role.Code AS previous_role,new_role.Code AS new_role,
          a.PreviousIsActive AS previous_is_active,a.NewIsActive AS new_is_active,
          a.CreatedAt AS created_at
        FROM dbo.UserSecurityAudit a
        JOIN dbo.Users target ON target.UserId=a.TargetUserId
        LEFT JOIN dbo.Users actor ON actor.UserId=a.ActorUserId
        LEFT JOIN dbo.Roles old_role ON old_role.RoleId=a.PreviousRoleId
        LEFT JOIN dbo.Roles new_role ON new_role.RoleId=a.NewRoleId
        WHERE (:target IS NULL OR a.TargetUserId=:target)
        ORDER BY a.CreatedAt DESC,a.AuditId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"target": target_user_id, "offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    result = []
    for row in rows:
        item = dict(row)
        item["target_username"] = decrypt_text(item.pop("target_email_ciphertext"))
        item["target_email"] = item["target_username"]
        actor_ciphertext = item.pop("actor_email_ciphertext")
        item["actor_username"] = decrypt_text(actor_ciphertext) if actor_ciphertext else None
        item["actor_email"] = item["actor_username"]
        result.append(item)
    return result
