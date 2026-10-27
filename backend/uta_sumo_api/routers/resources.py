from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_user, require_roles
from app.core.crypto import decrypt_text, encrypt_text, resource_name_lookup_hash
from app.core.pagination import apply_pagination_headers
from app.schemas.resources import (ParticipantUpdate, RegistrationResourcesInput, RobotInput,
                                   TeamInput, TeamUpdate)
from database import get_db

router = APIRouter(prefix="/api/v1", tags=["Recursos"])


def _name_conflict(resource_type: str, field: str):
    label = "equipo" if resource_type == "team" else "robot"
    return HTTPException(status_code=409, detail={
        "code": f"DUPLICATE_{resource_type.upper()}_NAME",
        "field": field,
        "message": f"Ya existe un {label} con ese nombre. Elige otro nombre.",
    })


def _name_exists(db: Session, resource_type: str, name: str, *, exclude_id: int | None = None) -> bool:
    if resource_type == "team":
        sql = "SELECT TOP (1) 1 FROM dbo.Teams WHERE NameLookupHash=:hash AND (:exclude_id IS NULL OR TeamId<>:exclude_id)"
    elif resource_type == "robot":
        sql = "SELECT TOP (1) 1 FROM dbo.Robots WHERE NameLookupHash=:hash AND (:exclude_id IS NULL OR RobotId<>:exclude_id)"
    else:
        raise ValueError("Tipo de recurso inválido.")
    return db.execute(text(sql), {"hash": resource_name_lookup_hash(name, resource_type),
                                  "exclude_id": exclude_id}).first() is not None


@router.get("/teams")
def list_teams(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
              user=Depends(get_current_user), db: Session = Depends(get_db)):
    where = "" if user["role"] in ("ADMIN", "EVENT_MANAGER") else "WHERE t.OwnerUserId=:owner"
    contact_phone = "t.ContactPhone" if user["role"] != "EVENT_MANAGER" else "CAST(NULL AS NVARCHAR(128))"
    total = db.execute(text(f"SELECT COUNT_BIG(*) FROM dbo.Teams t {where}"),
                       {"owner": user["user_id"]}).scalar_one()
    rows = db.execute(text(f"""
        SELECT t.TeamId AS id, t.Name AS name, t.InstitutionId AS institution_id,
               {contact_phone} AS contact_phone, t.OwnerUserId AS owner_user_id
        FROM dbo.Teams t {where}
        ORDER BY t.TeamId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"owner": user["user_id"], "offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [_decode_team(dict(r)) for r in rows]


def _decode_team(row):
    row["name"] = decrypt_text(row["name"])
    row["contact_phone"] = decrypt_text(row["contact_phone"])
    return row


def _decode_robot(row):
    row["name"] = decrypt_text(row["name"])
    row["description"] = decrypt_text(row["description"])
    return row


def _decode_participant(row):
    row["first_name"] = decrypt_text(row["first_name"])
    row["last_name"] = decrypt_text(row["last_name"])
    row["mobile_phone"] = decrypt_text(row["mobile_phone"])
    return row


@router.get("/teams/{team_id}")
def get_team(team_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    contact_phone = "ContactPhone" if user["role"] != "EVENT_MANAGER" else "CAST(NULL AS NVARCHAR(128))"
    row = db.execute(text(f"""
        SELECT TeamId AS id, Name AS name, InstitutionId AS institution_id,
               {contact_phone} AS contact_phone, OwnerUserId AS owner_user_id
        FROM dbo.Teams WHERE TeamId=:id
          AND (:admin=1 OR OwnerUserId=:owner)
    """), {"id": team_id, "admin": user["role"] in ("ADMIN", "EVENT_MANAGER"),
          "owner": user["user_id"]}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    return _decode_team(dict(row))


@router.post("/teams", status_code=201)
def create_team(payload: TeamInput, user=Depends(require_roles("PARTICIPANT", "ADMIN")), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre del equipo no puede estar vacío.")
    if _name_exists(db, "team", name):
        raise _name_conflict("team", "teamName")
    active = db.execute(text("SELECT 1 FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1"),
                        {"id": payload.institution_id}).first()
    if not active:
        raise HTTPException(status_code=422, detail="La institución no existe o está inactiva.")
    if user["role"] == "PARTICIPANT":
        own_institution = db.execute(text("SELECT InstitutionId FROM dbo.Participants WHERE UserId=:id"),
                                     {"id": user["user_id"]}).scalar_one_or_none()
        if own_institution != payload.institution_id:
            raise HTTPException(status_code=403, detail="El equipo debe pertenecer a la institución del perfil.")
    owner = user["user_id"] if user["role"] == "PARTICIPANT" else None
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Teams (Name, NameLookupHash, InstitutionId, ContactPhone, OwnerUserId)
            OUTPUT INSERTED.TeamId AS id, INSERTED.Name AS name,
              INSERTED.InstitutionId AS institution_id, INSERTED.ContactPhone AS contact_phone,
              INSERTED.OwnerUserId AS owner_user_id
            VALUES (:name,:name_hash,:institution,:phone,:owner)
        """), {"name": encrypt_text(name), "name_hash": resource_name_lookup_hash(name, "team"),
              "institution": payload.institution_id,
              "phone": encrypt_text(payload.contact_phone), "owner": owner}).mappings().one()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_conflict("team", "teamName")
    return _decode_team(dict(row))


@router.put("/teams/{team_id}")
def update_team(team_id: int, payload: TeamUpdate, user=Depends(require_roles("PARTICIPANT", "ADMIN")), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre del equipo no puede estar vacío.")
    if _name_exists(db, "team", name, exclude_id=team_id):
        raise _name_conflict("team", "teamName")
    admin = user["role"] == "ADMIN"
    if not admin:
        own_institution = db.execute(text("SELECT InstitutionId FROM dbo.Participants WHERE UserId=:id"),
                                     {"id": user["user_id"]}).scalar_one_or_none()
        if own_institution != payload.institution_id:
            raise HTTPException(status_code=403, detail="El equipo debe pertenecer a la institución del perfil.")
    try:
        row = db.execute(text("""
            UPDATE dbo.Teams SET Name=:name, NameLookupHash=:name_hash,
              InstitutionId=:institution, ContactPhone=:phone
            OUTPUT INSERTED.TeamId AS id, INSERTED.Name AS name,
              INSERTED.InstitutionId AS institution_id, INSERTED.ContactPhone AS contact_phone
            WHERE TeamId=:id AND (:admin=1 OR OwnerUserId=:owner)
        """), {"id": team_id, "name": encrypt_text(name), "name_hash": resource_name_lookup_hash(name, "team"),
              "institution": payload.institution_id,
              "phone": encrypt_text(payload.contact_phone), "admin": admin, "owner": user["user_id"]}).mappings().first()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="Equipo no encontrado.")
        active = db.execute(text("SELECT IsActive FROM dbo.Institutions WHERE InstitutionId=:id"),
                            {"id": payload.institution_id}).scalar_one_or_none()
        if not active:
            db.rollback()
            raise HTTPException(status_code=422, detail="La institución no existe o está inactiva.")
        db.commit()
        return _decode_team(dict(row))
    except IntegrityError:
        db.rollback()
        raise _name_conflict("team", "teamName")


@router.get("/robots")
def list_robots(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                user=Depends(get_current_user), db: Session = Depends(get_db)):
    where = "" if user["role"] in ("ADMIN", "EVENT_MANAGER") else "WHERE OwnerUserId=:owner"
    total = db.execute(text(f"SELECT COUNT_BIG(*) FROM dbo.Robots {where}"),
                       {"owner": user["user_id"]}).scalar_one()
    rows = db.execute(text(f"""
        SELECT RobotId AS id, Name AS name, RobotDescription AS description,
               OwnerUserId AS owner_user_id FROM dbo.Robots {where}
        ORDER BY RobotId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"owner": user["user_id"], "offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [_decode_robot(dict(r)) for r in rows]


@router.get("/robots/{robot_id}")
def get_robot(robot_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT RobotId AS id, Name AS name, RobotDescription AS description,
               OwnerUserId AS owner_user_id FROM dbo.Robots
        WHERE RobotId=:id AND (:admin=1 OR OwnerUserId=:owner)
    """), {"id": robot_id, "admin": user["role"] in ("ADMIN", "EVENT_MANAGER"),
          "owner": user["user_id"]}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Robot no encontrado.")
    return _decode_robot(dict(row))


@router.post("/robots", status_code=201)
def create_robot(payload: RobotInput, user=Depends(require_roles("PARTICIPANT", "ADMIN")), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre del robot no puede estar vacío.")
    if _name_exists(db, "robot", name):
        raise _name_conflict("robot", "robotName")
    owner = user["user_id"] if user["role"] == "PARTICIPANT" else None
    try:
        row = db.execute(text("""
            INSERT INTO dbo.Robots (Name, NameLookupHash, RobotDescription, OwnerUserId)
            OUTPUT INSERTED.RobotId AS id, INSERTED.Name AS name,
              INSERTED.RobotDescription AS description, INSERTED.OwnerUserId AS owner_user_id
            VALUES (:name,:name_hash,:description,:owner)
        """), {"name": encrypt_text(name), "name_hash": resource_name_lookup_hash(name, "robot"),
              "description": encrypt_text(payload.robot_description),
              "owner": owner}).mappings().one()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_conflict("robot", "robotName")
    return _decode_robot(dict(row))


@router.put("/robots/{robot_id}")
def update_robot(robot_id: int, payload: RobotInput, user=Depends(require_roles("PARTICIPANT", "ADMIN")), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre del robot no puede estar vacío.")
    if _name_exists(db, "robot", name, exclude_id=robot_id):
        raise _name_conflict("robot", "robotName")
    try:
        row = db.execute(text("""
            UPDATE dbo.Robots SET Name=:name, NameLookupHash=:name_hash, RobotDescription=:description
            OUTPUT INSERTED.RobotId AS id, INSERTED.Name AS name,
              INSERTED.RobotDescription AS description
            WHERE RobotId=:id AND (:admin=1 OR OwnerUserId=:owner)
        """), {"id": robot_id, "name": encrypt_text(name),
              "name_hash": resource_name_lookup_hash(name, "robot"),
              "description": encrypt_text(payload.robot_description), "admin": user["role"] == "ADMIN",
              "owner": user["user_id"]}).mappings().first()
    except IntegrityError:
        db.rollback()
        raise _name_conflict("robot", "robotName")
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Robot no encontrado.")
    db.commit()
    return _decode_robot(dict(row))


@router.post("/registration-resources", status_code=201)
def create_registration_resources(payload: RegistrationResourcesInput,
                                  user=Depends(require_roles("PARTICIPANT")),
                                  db: Session = Depends(get_db)):
    """Atomically create unique team and robot names used by a new registration."""
    team_name, robot_name = payload.team_name.strip(), payload.robot_name.strip()
    if not team_name:
        raise HTTPException(status_code=422, detail="El nombre del equipo no puede estar vacío.")
    if not robot_name:
        raise HTTPException(status_code=422, detail="El nombre del robot no puede estar vacío.")
    team_hash = resource_name_lookup_hash(team_name, "team")
    robot_hash = resource_name_lookup_hash(robot_name, "robot")
    if _name_exists(db, "team", team_name):
        raise _name_conflict("team", "teamName")
    if _name_exists(db, "robot", robot_name):
        raise _name_conflict("robot", "robotName")
    institution = db.execute(text("""
        SELECT InstitutionId FROM dbo.Participants WHERE UserId=:user_id
    """), {"user_id": user["user_id"]}).scalar_one_or_none()
    if institution != payload.institution_id:
        raise HTTPException(status_code=403, detail="El equipo debe pertenecer a la institución del perfil.")
    if db.execute(text("SELECT 1 FROM dbo.Institutions WHERE InstitutionId=:id AND IsActive=1"),
                  {"id": payload.institution_id}).first() is None:
        raise HTTPException(status_code=422, detail="La institución no existe o está inactiva.")
    try:
        team = db.execute(text("""
            INSERT INTO dbo.Teams(Name,NameLookupHash,InstitutionId,ContactPhone,OwnerUserId)
            OUTPUT INSERTED.TeamId AS id,INSERTED.Name AS name,INSERTED.InstitutionId AS institution_id,
              INSERTED.ContactPhone AS contact_phone,INSERTED.OwnerUserId AS owner_user_id
            VALUES(:name,:name_hash,:institution,:phone,:owner)
        """), {"name": encrypt_text(team_name), "name_hash": team_hash,
              "institution": payload.institution_id, "phone": encrypt_text(payload.contact_phone),
              "owner": user["user_id"]}).mappings().one()
        robot = db.execute(text("""
            INSERT INTO dbo.Robots(Name,NameLookupHash,RobotDescription,OwnerUserId)
            OUTPUT INSERTED.RobotId AS id,INSERTED.Name AS name,INSERTED.RobotDescription AS description,
              INSERTED.OwnerUserId AS owner_user_id
            VALUES(:name,:name_hash,:description,:owner)
        """), {"name": encrypt_text(robot_name), "name_hash": robot_hash,
              "description": encrypt_text(payload.robot_description), "owner": user["user_id"]}).mappings().one()
        db.commit()
    except IntegrityError:
        db.rollback()
        if _name_exists(db, "team", team_name):
            raise _name_conflict("team", "teamName")
        if _name_exists(db, "robot", robot_name):
            raise _name_conflict("robot", "robotName")
        raise HTTPException(status_code=409, detail="No se pudieron guardar los nombres; vuelve a intentarlo.")
    return {"team": _decode_team(dict(team)), "robot": _decode_robot(dict(robot))}


@router.get("/participants/me")
def own_participant(user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT ParticipantId AS id, FirstName AS first_name, LastName AS last_name,
          MobilePhone AS mobile_phone, InstitutionId AS institution_id
        FROM dbo.Participants WHERE UserId=:id
    """), {"id": user["user_id"]}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Perfil de participante no encontrado.")
    return _decode_participant(dict(row))


@router.put("/participants/me")
def update_own_participant(payload: ParticipantUpdate,
                           user=Depends(require_roles("PARTICIPANT")), db: Session = Depends(get_db)):
    row = db.execute(text("""
        UPDATE dbo.Participants SET FirstName=:first, LastName=:last, MobilePhone=:phone
        OUTPUT INSERTED.ParticipantId AS id, INSERTED.FirstName AS first_name,
          INSERTED.LastName AS last_name, INSERTED.MobilePhone AS mobile_phone,
          INSERTED.InstitutionId AS institution_id
        WHERE UserId=:user_id
    """), {"user_id": user["user_id"], "first": encrypt_text(payload.first_name.strip()),
          "last": encrypt_text(payload.last_name.strip()), "phone": encrypt_text(payload.mobile_phone)}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Perfil de participante no encontrado.")
    db.execute(text("UPDATE dbo.Users SET FirstName=:first, LastName=:last WHERE UserId=:user_id"),
               {"user_id": user["user_id"], "first": encrypt_text(payload.first_name.strip()),
                "last": encrypt_text(payload.last_name.strip())})
    db.commit()
    return _decode_participant(dict(row))


@router.get("/participants")
def list_participants(response: Response, page: int = Query(1, ge=1, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                      user=Depends(require_roles("ADMIN", "EVENT_MANAGER")),
                      db: Session = Depends(get_db)):
    mobile_phone = "MobilePhone" if user["role"] == "ADMIN" else "CAST(NULL AS NVARCHAR(128))"
    total = db.execute(text("SELECT COUNT_BIG(*) FROM dbo.Participants")).scalar_one()
    rows = db.execute(text(f"""
        SELECT ParticipantId AS id, FirstName AS first_name, LastName AS last_name,
          {mobile_phone} AS mobile_phone, InstitutionId AS institution_id, UserId AS user_id
        FROM dbo.Participants ORDER BY ParticipantId DESC
        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"offset": (page-1)*limit, "limit": limit}).mappings().all()
    apply_pagination_headers(response, total=int(total), page=page, limit=limit)
    return [_decode_participant(dict(r)) for r in rows]
