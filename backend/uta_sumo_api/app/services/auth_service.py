from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.crypto import email_lookup_hash, decrypt_text


def find_user_for_login(db: Session, email: str):
    row = db.execute(text("""
        SELECT u.UserId, u.EmailCiphertext, u.PasswordHash, u.FirstName, u.LastName,
               u.IsActive, u.TokenVersion, u.MustChangePassword, r.Code AS RoleCode
        FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        WHERE u.EmailLookupHash=:lookup
    """), {"lookup": email_lookup_hash(email)}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["Email"] = decrypt_text(result.pop("EmailCiphertext"))
    result["FirstName"] = decrypt_text(result["FirstName"])
    result["LastName"] = decrypt_text(result["LastName"])
    return result


def find_active_user(db: Session, user_id: int):
    row = db.execute(text("""
        SELECT u.UserId AS user_id, u.EmailCiphertext AS email_ciphertext,
               u.TokenVersion AS token_version,
               u.MustChangePassword AS must_change_password,
               u.FirstName AS first_name, u.LastName AS last_name,
               r.Code AS role
        FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        WHERE u.UserId=:user_id AND u.IsActive=1
    """), {"user_id": user_id}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["email"] = decrypt_text(result.pop("email_ciphertext"))
    result["username"] = result["email"]
    result["first_name"] = decrypt_text(result["first_name"])
    result["last_name"] = decrypt_text(result["last_name"])
    return result
