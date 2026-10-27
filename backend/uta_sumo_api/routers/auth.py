import secrets

from fastapi import APIRouter, Depends, HTTPException
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (create_access_token, hash_password, verify_password,
                               password_hash_needs_upgrade)
from app.core.crypto import decrypt_text, email_lookup_hash, encrypt_text
from app.core.config import EMAIL_CHECK_DELIVERABILITY, GOOGLE_CLIENT_ID, SECRET_KEY
from app.core.password_policy import validate_password
from app.dependencies.auth import get_authenticated_user, get_current_user, require_roles
from app.schemas.auth import (
    AuthResponse, ChangePasswordRequest, GoogleAuthRequest, LoginRequest, RegisterRequest,
    UserResponse,
)
from app.services.auth_service import find_user_for_login
from app.services.google_identity import InvalidGoogleToken, verify_google_id_token
from database import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])


def _validated_email(value: str) -> str:
    try:
        validated = validate_email(
            value, check_deliverability=EMAIL_CHECK_DELIVERABILITY,
            timeout=5, globally_deliverable=True,
        )
    except EmailNotValidError:
        raise HTTPException(status_code=422, detail="El correo o su dominio no es válido.")
    return validated.normalized.casefold()


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if len(SECRET_KEY) < 32:
        raise HTTPException(status_code=503, detail="La autenticación no está configurada en el servidor.")
    if not payload.first_name.strip() or not payload.last_name.strip():
        raise HTTPException(status_code=422, detail="Los nombres son obligatorios.")
    email = _validated_email(str(payload.email))
    institution = db.execute(text(
        "SELECT InstitutionId FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1"
    ), {"id": payload.institution_id}).first()
    role = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code='PARTICIPANT'")).first()
    if not institution:
        raise HTTPException(status_code=422, detail="La institución no existe o está inactiva.")
    if not role:
        raise HTTPException(status_code=503, detail="El rol de participante no está configurado.")
    try:
        result = db.execute(text("""
            INSERT INTO dbo.Users (EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId)
            OUTPUT INSERTED.UserId
            VALUES (:email,:lookup,:password_hash,:first_name,:last_name,:role_id)
        """), {
            "email": encrypt_text(email), "lookup": email_lookup_hash(email),
            "password_hash": hash_password(payload.password),
            "first_name": encrypt_text(payload.first_name.strip()),
            "last_name": encrypt_text(payload.last_name.strip()),
            "role_id": role[0],
        })
        user_id = result.scalar_one()
        db.execute(text("""
            INSERT INTO dbo.Participants (FirstName, LastName, MobilePhone, InstitutionId, UserId)
            VALUES (:first_name, :last_name, :phone, :institution_id, :user_id)
        """), {
            "first_name": encrypt_text(payload.first_name.strip()),
            "last_name": encrypt_text(payload.last_name.strip()),
            "phone": encrypt_text(payload.mobile_phone), "institution_id": payload.institution_id,
            "user_id": user_id,
        })
        db.execute(text("""
            INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode,NewRoleId,NewIsActive)
            VALUES (:target,:actor,'ACCOUNT_CREATED',:role,1)
        """), {"target": user_id, "actor": user_id, "role": role[0]})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No fue posible registrar la cuenta con esos datos.")
    except Exception:
        db.rollback()
        raise
    user = UserResponse(user_id=user_id, email=email, username=email,
                        first_name=payload.first_name.strip(), last_name=payload.last_name.strip(),
                        role="PARTICIPANT")
    return AuthResponse(access_token=create_access_token(user_id, "PARTICIPANT", 0), user=user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    if len(SECRET_KEY) < 32:
        raise HTTPException(status_code=503, detail="La autenticación no está configurada en el servidor.")
    row = find_user_for_login(db, str(payload.email))
    if not row or not row["IsActive"] or not verify_password(payload.password, row["PasswordHash"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña no válidos.",
                            headers={"WWW-Authenticate": "Bearer"})
    if password_hash_needs_upgrade(row["PasswordHash"]):
        db.execute(text("UPDATE dbo.Users SET PasswordHash=:hash WHERE UserId=:id"),
                   {"id": row["UserId"], "hash": hash_password(payload.password)})
        db.commit()
    user = UserResponse(user_id=row["UserId"], email=row["Email"], username=row["Email"],
                        first_name=row["FirstName"], last_name=row["LastName"], role=row["RoleCode"],
                        must_change_password=bool(row["MustChangePassword"]))
    return AuthResponse(access_token=create_access_token(user.user_id, user.role, row["TokenVersion"]), user=user)


@router.post("/google", response_model=AuthResponse)
def google_login(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Create or authenticate a PARTICIPANT from a verified Google ID token."""
    if len(SECRET_KEY) < 32:
        raise HTTPException(status_code=503, detail="La autenticación no está configurada en el servidor.")
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="El acceso con Google no está configurado en el servidor.")
    try:
        claims = verify_google_id_token(payload.id_token, GOOGLE_CLIENT_ID)
        email = _validated_email(claims["email"])
    except InvalidGoogleToken:
        raise HTTPException(status_code=401, detail="La credencial de Google no es válida o expiró.")

    subject = claims["sub"]
    identity = db.execute(text("""
        SELECT u.UserId,u.IsActive,u.TokenVersion,r.Code AS RoleCode,
               u.EmailCiphertext,u.FirstName,u.LastName
        FROM dbo.UserExternalIdentities i
        JOIN dbo.Users u ON u.UserId=i.UserId
        JOIN dbo.Roles r ON r.RoleId=u.RoleId
        WHERE i.ProviderCode='GOOGLE' AND i.ProviderSubject=:subject
    """), {"subject": subject}).mappings().first()

    if identity:
        if not identity["IsActive"]:
            raise HTTPException(status_code=403, detail="La cuenta está desactivada.")
        if identity["RoleCode"] != "PARTICIPANT":
            raise HTTPException(status_code=403, detail="El acceso con Google está reservado a participantes.")
        user_id = identity["UserId"]
        role_code = identity["RoleCode"]
        token_version = identity["TokenVersion"]
        user_email = decrypt_text(identity["EmailCiphertext"])
        first_name = decrypt_text(identity["FirstName"])
        last_name = decrypt_text(identity["LastName"])
    else:
        # Never attach a Google identity to an existing email-only account
        # implicitly. The owner must authenticate first and explicitly link it.
        existing = find_user_for_login(db, email)
        if existing:
            raise HTTPException(status_code=409, detail=(
                "Ya existe una cuenta con ese correo. Inicia sesión o recupera tu contraseña."
            ))
        if payload.institution_id is None:
            raise HTTPException(status_code=422, detail="Selecciona una institución para crear tu perfil.")
        institution = db.execute(text(
            "SELECT InstitutionId FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1"
        ), {"id": payload.institution_id}).first()
        role = db.execute(text("SELECT RoleId FROM dbo.Roles WHERE Code='PARTICIPANT'")).first()
        if not institution:
            raise HTTPException(status_code=422, detail="La institución no existe o está inactiva.")
        if not role:
            raise HTTPException(status_code=503, detail="El rol de participante no está configurado.")

        display_name = (claims.get("name") or "").strip()
        first_name = (claims.get("given_name") or (display_name.split(" ", 1)[0] if display_name else "")
                      or email.split("@", 1)[0])[:100]
        last_name = (claims.get("family_name") or
                     (display_name.split(" ", 1)[1] if " " in display_name else "Usuario"))[:100]
        try:
            result = db.execute(text("""
                INSERT INTO dbo.Users (EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId)
                OUTPUT INSERTED.UserId
                VALUES (:email,:lookup,:password_hash,:first_name,:last_name,:role_id)
            """), {
                "email": encrypt_text(email), "lookup": email_lookup_hash(email),
                # A random, discarded credential prevents password login for
                # Google-only accounts without ever storing a Google password.
                "password_hash": hash_password(secrets.token_urlsafe(48)),
                "first_name": encrypt_text(first_name), "last_name": encrypt_text(last_name),
                "role_id": role[0],
            })
            user_id = result.scalar_one()
            db.execute(text("""
                INSERT INTO dbo.Participants (FirstName,LastName,InstitutionId,UserId)
                VALUES (:first_name,:last_name,:institution_id,:user_id)
            """), {"first_name": encrypt_text(first_name), "last_name": encrypt_text(last_name),
                  "institution_id": payload.institution_id, "user_id": user_id})
            db.execute(text("""
                INSERT INTO dbo.UserExternalIdentities (UserId,ProviderCode,ProviderSubject)
                VALUES (:user_id,'GOOGLE',:subject)
            """), {"user_id": user_id, "subject": subject})
            db.execute(text("""
                INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode,NewRoleId,NewIsActive)
                VALUES (:target,:actor,'ACCOUNT_CREATED',:role,1)
            """), {"target": user_id, "actor": user_id, "role": role[0]})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="No fue posible crear la cuenta con Google.")
        role_code = "PARTICIPANT"
        token_version = 0
        user_email = email

    user = UserResponse(user_id=user_id, email=user_email, username=user_email,
                        first_name=first_name, last_name=last_name, role=role_code)
    return AuthResponse(access_token=create_access_token(user_id, role_code, token_version), user=user)


@router.post("/google/link", status_code=204)
def link_google_account(payload: GoogleAuthRequest, user=Depends(require_roles("PARTICIPANT")),
                        db: Session = Depends(get_db)):
    """Link a verified Google identity after authenticating to this account."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="El acceso con Google no está configurado en el servidor.")
    try:
        claims = verify_google_id_token(payload.id_token, GOOGLE_CLIENT_ID)
        google_email = _validated_email(claims["email"])
    except InvalidGoogleToken:
        raise HTTPException(status_code=401, detail="La credencial de Google no es válida o expiró.")
    row = db.execute(text("SELECT EmailCiphertext FROM dbo.Users WHERE UserId=:id AND IsActive=1"),
                     {"id": user["user_id"]}).first()
    if not row or decrypt_text(row[0]).casefold() != google_email.casefold():
        raise HTTPException(status_code=409, detail="El correo Google debe coincidir con el correo de esta cuenta.")
    try:
        db.execute(text("""
            INSERT INTO dbo.UserExternalIdentities (UserId,ProviderCode,ProviderSubject)
            VALUES (:user_id,'GOOGLE',:subject)
        """), {"user_id": user["user_id"], "subject": claims["sub"]})
        db.execute(text("""
            INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode)
            VALUES (:target,:actor,'ACCOUNT_UPDATED')
        """), {"target": user["user_id"], "actor": user["user_id"]})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esta identidad de Google ya está vinculada a una cuenta.")
    return None


@router.get("/me", response_model=UserResponse)
def me(user=Depends(get_authenticated_user)):
    return user


@router.post("/change-password", status_code=204)
def change_password(payload: ChangePasswordRequest, user=Depends(get_authenticated_user),
                    db: Session = Depends(get_db)):
    try:
        validate_password(payload.new_password, user.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = db.execute(text("SELECT PasswordHash FROM dbo.Users WHERE UserId=:id"),
                     {"id": user["user_id"]}).first()
    if row is None or not verify_password(payload.current_password, row[0]):
        raise HTTPException(status_code=400, detail="La contraseña actual no es válida.")
    if verify_password(payload.new_password, row[0]):
        raise HTTPException(status_code=422, detail="La nueva contraseña debe ser diferente a la actual.")
    db.execute(text("UPDATE dbo.Users SET PasswordHash=:hash, MustChangePassword=0, TokenVersion=TokenVersion+1 WHERE UserId=:id"),
               {"hash": hash_password(payload.new_password), "id": user["user_id"]})
    db.execute(text("""
        INSERT INTO dbo.UserSecurityAudit(TargetUserId,ActorUserId,ActionCode)
        VALUES (:target,:actor,'PASSWORD_CHANGED')
    """), {"target": user["user_id"], "actor": user["user_id"]})
    db.commit()
    return None
