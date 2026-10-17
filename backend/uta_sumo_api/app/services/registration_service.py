from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.crypto import encrypt_text


def change_registration_status(db: Session, registration_id: int, status_code: str,
                              actor_id: int, comments: str | None = None) -> None:
    old = db.execute(text("""
        SELECT s.StatusId FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId WHERE r.RegistrationId=:id
    """), {"id": registration_id}).scalar_one_or_none()
    new_id = db.execute(text("SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code=:code"),
                        {"code": status_code}).scalar_one_or_none()
    if old is None or new_id is None:
        raise HTTPException(status_code=404, detail="Inscripción o estado no encontrado.")
    db.execute(text("UPDATE dbo.Registrations SET StatusId=:new WHERE RegistrationId=:id"),
               {"new": new_id, "id": registration_id})
    db.execute(text("""
        INSERT INTO dbo.StatusHistory (RegistrationId,PreviousStatusId,NewStatusId,ChangedByUserId,Comments)
        VALUES (:id,:old,:new,:actor,:comments)
    """), {"id": registration_id, "old": old, "new": new_id,
          "actor": actor_id, "comments": encrypt_text(comments)})
