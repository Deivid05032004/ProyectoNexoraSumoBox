from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import ALGORITHM, SECRET_KEY
from database import get_db
from app.services.auth_service import find_active_user

bearer = HTTPBearer(auto_error=False)


def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales no válidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", ""))
        token_version = int(payload.get("ver", 0))
    except (JWTError, TypeError, ValueError):
        raise unauthorized
    user = find_active_user(db, user_id)
    if user is None or user["token_version"] != token_version:
        raise unauthorized
    return dict(user)


def get_current_user(user=Depends(get_authenticated_user)):
    if user.get("must_change_password"):
        raise HTTPException(status_code=403, detail="Actualiza tu contraseña antes de continuar.")
    return user


def require_roles(*roles: str):
    def dependency(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="No tiene permisos para esta operación.")
        if user.get("must_change_password"):
            raise HTTPException(status_code=403, detail="Actualiza tu contraseña antes de continuar.")
        return user
    return dependency
