"""Administrative management of event/category tournament groups."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.core.pagination import apply_pagination_headers
from app.dependencies.auth import require_roles
from database import get_db

router = APIRouter(prefix="/api/v1/admin/events", tags=["Grupos del torneo"])
STAFF = ("ADMIN", "EVENT_MANAGER")


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=20)
    max_teams: int = Field(ge=1, le=64)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("El nombre del grupo es obligatorio.")
        return value

    @field_validator("code")
    @classmethod
    def clean_code(cls, value):
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{1,20}", value):
            raise ValueError("El código solo puede contener letras, números, guion y guion bajo.")
        return value


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, min_length=1, max_length=20)
    max_teams: int | None = Field(default=None, ge=1, le=64)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("El nombre del grupo es obligatorio.")
        return value

    @field_validator("code")
    @classmethod
    def clean_code(cls, value):
        if value is None:
            return value
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{1,20}", value):
            raise ValueError("El código solo puede contener letras, números, guion y guion bajo.")
        return value


class RegistrationAssignment(BaseModel):
    registration_id: int = Field(gt=0)


def _validate_event_category(db: Session, event_id: int, category_id: int) -> None:
    exists = db.execute(text("""
      SELECT 1 FROM dbo.EventCategories ec
      JOIN dbo.Events e ON e.EventId=ec.EventId
      JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
      WHERE ec.EventId=:event AND ec.CategoryId=:category
    """), {"event": event_id, "category": category_id}).first()
    if not exists:
        raise HTTPException(404, "El evento o la categoría asociada no existe.")


def _tournament_started(db: Session, event_id: int, category_id: int, *, lock: bool = False) -> bool:
    lock_hint = " WITH (UPDLOCK,HOLDLOCK)" if lock else ""
    state = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState{lock_hint}
      WHERE EventId=:event AND CategoryId=:category
    """.format(lock_hint=lock_hint)), {"event": event_id, "category": category_id}).scalar_one_or_none()
    if state is not None and state != "GROUP":
        return True
    # Once a group-stage schedule exists, changing memberships would leave its
    # fixtures inconsistent even though no score has been entered yet.
    if db.execute(text("""
      SELECT TOP (1) 1 FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE r.EventId=:event AND r.CategoryId=:category AND m.TournamentGroupId IS NOT NULL
    """), {"event": event_id, "category": category_id}).first():
        return True
    return bool(db.execute(text("""
      SELECT TOP (1) 1
      FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode<>'MANUAL'
        AND (m.MatchStatus<>'SCHEDULED' OR EXISTS(
          SELECT 1 FROM dbo.ScoreEntries s WHERE s.MatchId=m.MatchId
        ))
    """), {"event": event_id, "category": category_id}).first())


def _group_details(db: Session, group_ids: list[int]) -> dict[int, dict]:
    if not group_ids:
        return {}
    group_query = text("""
                SELECT g.TournamentGroupId AS id,g.EventId AS event_id,g.CategoryId AS category_id,
                  g.GroupName AS name,g.GroupCode AS code,g.MaxTeams AS max_teams,
                  g.CreatedAt AS created_at,g.UpdatedAt AS updated_at,
                  (SELECT COUNT(*) FROM dbo.TournamentGroupRegistrations a
                   WHERE a.TournamentGroupId=g.TournamentGroupId) AS assigned_count
                FROM dbo.TournamentGroups g WHERE g.TournamentGroupId IN :ids
              """).bindparams(bindparam("ids", expanding=True))
    groups = {int(row["id"]): {**dict(row), "participants": [], "teams": []}
              for row in db.execute(group_query, {"ids": group_ids}).mappings().all()}
    if not groups:
        return groups

    # Use explicit expanding bind so this remains safe for any group count.
    query = text("""
      SELECT a.TournamentGroupId AS group_id,r.RegistrationId AS registration_id,
        CONVERT(VARCHAR(36),r.RegistrationCode) AS registration_code,st.Code AS registration_status,
        r.TeamId AS team_id,t.Name AS team_name,r.RobotId AS robot_id,rb.Name AS robot_name,
        i.Name AS institution,
        p.ParticipantId AS participant_id,p.FirstName AS first_name,p.LastName AS last_name,
        p.MobilePhone AS mobile_phone,pi.Name AS participant_institution,rp.Role AS participant_role,
        rp.RegistrationPosition AS participant_position
      FROM dbo.TournamentGroupRegistrations a
      JOIN dbo.TournamentGroups g ON g.TournamentGroupId=a.TournamentGroupId
      JOIN dbo.Registrations r ON r.RegistrationId=a.RegistrationId
      JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId
      JOIN dbo.Teams t ON t.TeamId=r.TeamId JOIN dbo.Robots rb ON rb.RobotId=r.RobotId
      JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      LEFT JOIN dbo.RegistrationParticipants rp ON rp.RegistrationId=r.RegistrationId
      LEFT JOIN dbo.Participants p ON p.ParticipantId=rp.ParticipantId
      LEFT JOIN dbo.Institutions pi ON pi.InstitutionId=p.InstitutionId
      WHERE a.TournamentGroupId IN :ids
      ORDER BY g.GroupName,t.Name,r.RegistrationId,rp.RegistrationPosition,rp.ParticipantId
    """).bindparams(bindparam("ids", expanding=True))
    rows = db.execute(query, {"ids": list(groups)}).mappings().all()
    for row in rows:
        group = groups[int(row["group_id"])]
        registration_id = int(row["registration_id"])
        team = next((item for item in group["teams"] if item["registration_id"] == registration_id), None)
        if team is None:
            team = {
                "registration_id": registration_id,
                "registration_code": row["registration_code"],
                "registration_status": row["registration_status"],
                "team_id": int(row["team_id"]), "team": decrypt_text(row["team_name"]),
                "robot_id": int(row["robot_id"]), "robot": decrypt_text(row["robot_name"]),
                "institution": row["institution"], "participants": [],
            }
            group["teams"].append(team)
        if row["participant_id"] is not None:
            participant = {
                "id": int(row["participant_id"]),
                "name": f"{decrypt_text(row['first_name'])} {decrypt_text(row['last_name'])}".strip(),
                "institution": row["participant_institution"],
                "role": row["participant_role"],
                "position": row["participant_position"],
                "team": team["team"],
            }
            team["participants"].append(participant)
            group["participants"].append(participant)
    for group in groups.values():
        group["assigned_count"] = len(group["teams"])
    return groups


def _group_locked(db: Session, event_id: int, category_id: int, *, lock: bool = False) -> bool:
    return _tournament_started(db, event_id, category_id, lock=lock)


@router.get("/{event_id}/categories/{category_id}/tournament-groups")
def list_groups(event_id: int, category_id: int, response: Response,
                user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    rows = db.execute(text("""
      SELECT TournamentGroupId AS id FROM dbo.TournamentGroups
      WHERE EventId=:event AND CategoryId=:category ORDER BY GroupName,TournamentGroupId
    """), {"event": event_id, "category": category_id}).mappings().all()
    details = _group_details(db, [int(row["id"]) for row in rows])
    locked = _group_locked(db, event_id, category_id)
    groups = []
    for row in rows:
        item = {**details[int(row["id"])], "locked": locked}
        # The group board only needs team and robot labels. Keep personal roster
        # data behind the dedicated /participants endpoint.
        item.pop("participants", None)
        for team in item["teams"]:
            team.pop("participants", None)
        groups.append(item)
    return {"event_id": event_id, "category_id": category_id, "locked": locked,
            "lock_reason": "El torneo ya inició; los grupos y asignaciones están protegidos." if locked else None,
            "groups": groups}


@router.get("/{event_id}/categories/{category_id}/tournament-groups/eligible-registrations")
def eligible_registrations(event_id: int, category_id: int, response: Response,
                           page: int = Query(1, ge=1), limit: int = Query(5, ge=1, le=100),
                           _user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    where = """
      FROM dbo.Registrations r
      JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
      JOIN dbo.Teams t ON t.TeamId=r.TeamId JOIN dbo.Robots rb ON rb.RobotId=r.RobotId
      JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      WHERE r.EventId=:event AND r.CategoryId=:category
        AND NOT EXISTS(SELECT 1 FROM dbo.TournamentGroupRegistrations a WHERE a.RegistrationId=r.RegistrationId)
    """
    params = {"event": event_id, "category": category_id}
    total = int(db.execute(text(f"SELECT COUNT_BIG(*) {where}"), params).scalar_one())
    rows = db.execute(text(f"""
      SELECT r.RegistrationId AS registration_id,CONVERT(VARCHAR(36),r.RegistrationCode) AS registration_code,
        r.TeamId AS team_id,t.Name AS team,r.RobotId AS robot_id,rb.Name AS robot,
        i.Name AS institution,st.Code AS status,
        (SELECT COUNT(*) FROM dbo.RegistrationParticipants rp WHERE rp.RegistrationId=r.RegistrationId) AS people_count
      {where}
      ORDER BY t.Name,r.RegistrationId OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {**params, "offset": (page-1)*limit, "limit": limit}).mappings().all()
    items = [{**dict(row), "team": decrypt_text(row["team"]), "robot": decrypt_text(row["robot"])} for row in rows]
    apply_pagination_headers(response, total=total, page=page, limit=limit)
    return {"items": items, "page": page, "page_size": limit, "total": total,
            "total_pages": (total+limit-1)//limit}


@router.post("/{event_id}/categories/{category_id}/tournament-groups", status_code=201)
def create_group(event_id: int, category_id: int, payload: GroupCreate,
                 user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    if _group_locked(db, event_id, category_id, lock=True):
        raise HTTPException(409, "El torneo ya inició; no se pueden crear grupos.")
    try:
        group_id = db.execute(text("""
          INSERT dbo.TournamentGroups(EventId,CategoryId,GroupName,GroupCode,MaxTeams,CreatedByUserId,UpdatedByUserId)
          OUTPUT INSERTED.TournamentGroupId
          VALUES(:event,:category,:name,:code,:capacity,:actor,:actor)
        """), {"event": event_id, "category": category_id, "name": payload.name,
              "code": payload.code, "capacity": payload.max_teams, "actor": user["user_id"]}).scalar_one()
        db.commit()
        return _group_details(db, [int(group_id)])[int(group_id)]
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ya existe un grupo con ese nombre o código en esta categoría.") from exc
    except Exception:
        db.rollback()
        raise


@router.patch("/{event_id}/categories/{category_id}/tournament-groups/{group_id}")
def update_group(event_id: int, category_id: int, group_id: int, payload: GroupUpdate,
                 user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    if _group_locked(db, event_id, category_id, lock=True):
        raise HTTPException(409, "El torneo ya inició; no se pueden editar los grupos.")
    current = db.execute(text("""
      SELECT g.MaxTeams,(SELECT COUNT(*) FROM dbo.TournamentGroupRegistrations a
        WHERE a.TournamentGroupId=g.TournamentGroupId) AS assigned_count
      FROM dbo.TournamentGroups g WITH (UPDLOCK,HOLDLOCK)
      WHERE g.TournamentGroupId=:group AND g.EventId=:event AND g.CategoryId=:category
    """), {"group": group_id, "event": event_id, "category": category_id}).mappings().first()
    if not current:
        raise HTTPException(404, "No se encontró el grupo de esta categoría.")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "Indica al menos un dato para actualizar el grupo.")
    capacity = data.get("max_teams", int(current["MaxTeams"]))
    if capacity < int(current["assigned_count"]):
        raise HTTPException(409, "La capacidad no puede ser menor a los equipos que ya están asignados.")
    try:
        data.update({"group": group_id, "event": event_id, "category": category_id,
                     "actor": user["user_id"], "capacity": capacity})
        db.execute(text("""
          UPDATE dbo.TournamentGroups SET
            GroupName=COALESCE(:name,GroupName),GroupCode=COALESCE(:code,GroupCode),
            MaxTeams=:capacity,UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE TournamentGroupId=:group AND EventId=:event AND CategoryId=:category
        """), {**data, "name": data.get("name"), "code": data.get("code")})
        db.commit()
        return _group_details(db, [group_id])[group_id]
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ya existe un grupo con ese nombre o código en esta categoría.") from exc
    except Exception:
        db.rollback()
        raise


@router.delete("/{event_id}/categories/{category_id}/tournament-groups/{group_id}", status_code=204)
def delete_group(event_id: int, category_id: int, group_id: int,
                 user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    if _group_locked(db, event_id, category_id, lock=True):
        raise HTTPException(409, "El torneo ya inició; no se pueden eliminar los grupos.")
    result = db.execute(text("""
      DELETE dbo.TournamentGroups WHERE TournamentGroupId=:group AND EventId=:event AND CategoryId=:category
    """), {"group": group_id, "event": event_id, "category": category_id})
    if not result.rowcount:
        db.rollback()
        raise HTTPException(404, "No se encontró el grupo de esta categoría.")
    db.commit()
    return Response(status_code=204)


@router.get("/{event_id}/categories/{category_id}/tournament-groups/{group_id}/participants")
def group_participants(event_id: int, category_id: int, group_id: int,
                       _user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    exists = db.execute(text("""
      SELECT 1 FROM dbo.TournamentGroups WHERE TournamentGroupId=:group AND EventId=:event AND CategoryId=:category
    """), {"group": group_id, "event": event_id, "category": category_id}).first()
    if not exists:
        raise HTTPException(404, "No se encontró el grupo de esta categoría.")
    group = _group_details(db, [group_id])[group_id]
    return {"group_id": group_id, "participants": group["participants"], "teams": group["teams"]}


@router.post("/{event_id}/categories/{category_id}/tournament-groups/{group_id}/registrations", status_code=201)
def assign_registration(event_id: int, category_id: int, group_id: int,
                        payload: RegistrationAssignment,
                        user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    try:
        group = db.execute(text("""
          SELECT g.MaxTeams FROM dbo.TournamentGroups g WITH (UPDLOCK,HOLDLOCK)
          WHERE g.TournamentGroupId=:group AND g.EventId=:event AND g.CategoryId=:category
        """), {"group": group_id, "event": event_id, "category": category_id}).mappings().first()
        if not group:
            raise HTTPException(404, "No se encontró el grupo de esta categoría.")
        if _tournament_started(db, event_id, category_id, lock=True):
            raise HTTPException(409, "El torneo ya inició; no se pueden cambiar las asignaciones.")
        registration = db.execute(text("""
          SELECT r.RegistrationId FROM dbo.Registrations r WITH (UPDLOCK,HOLDLOCK)
          JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
          WHERE r.RegistrationId=:registration AND r.EventId=:event AND r.CategoryId=:category
        """), {"registration": payload.registration_id, "event": event_id, "category": category_id}).scalar_one_or_none()
        if registration is None:
            raise HTTPException(422, "Selecciona una inscripción aprobada que pertenezca a este evento y categoría.")
        count = int(db.execute(text("""
          SELECT COUNT(*) FROM dbo.TournamentGroupRegistrations WITH (UPDLOCK,HOLDLOCK)
          WHERE TournamentGroupId=:group
        """), {"group": group_id}).scalar_one())
        if count >= int(group["MaxTeams"]):
            raise HTTPException(409, "El grupo alcanzó su capacidad máxima de equipos.")
        existing = db.execute(text("""
          SELECT g.GroupName FROM dbo.TournamentGroupRegistrations a
          JOIN dbo.TournamentGroups g ON g.TournamentGroupId=a.TournamentGroupId
          WHERE a.RegistrationId=:registration
        """), {"registration": payload.registration_id}).scalar_one_or_none()
        if existing:
            raise HTTPException(409, f"Esta inscripción ya está asignada al grupo {existing}.")
        db.execute(text("""
          INSERT dbo.TournamentGroupRegistrations(TournamentGroupId,RegistrationId,AssignedByUserId)
          VALUES(:group,:registration,:actor)
        """), {"group": group_id, "registration": payload.registration_id, "actor": user["user_id"]})
        db.commit()
        return _group_details(db, [group_id])[group_id]
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "La inscripción ya está asignada a un grupo o alcanzó la capacidad.") from exc
    except Exception:
        db.rollback()
        raise


@router.put("/{event_id}/categories/{category_id}/tournament-groups/{group_id}/registrations/{registration_id}")
def move_registration(event_id: int, category_id: int, group_id: int, registration_id: int,
                      user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    try:
        target = db.execute(text("""
          SELECT MaxTeams FROM dbo.TournamentGroups WITH (UPDLOCK,HOLDLOCK)
          WHERE TournamentGroupId=:group AND EventId=:event AND CategoryId=:category
        """), {"group": group_id, "event": event_id, "category": category_id}).mappings().first()
        if not target:
            raise HTTPException(404, "No se encontró el grupo de destino.")
        if _tournament_started(db, event_id, category_id, lock=True):
            raise HTTPException(409, "El torneo ya inició; no se pueden cambiar las asignaciones.")
        current = db.execute(text("""
          SELECT a.TournamentGroupId FROM dbo.TournamentGroupRegistrations a WITH (UPDLOCK,HOLDLOCK)
          JOIN dbo.TournamentGroups g ON g.TournamentGroupId=a.TournamentGroupId
          WHERE a.RegistrationId=:registration AND g.EventId=:event AND g.CategoryId=:category
        """), {"registration": registration_id, "event": event_id, "category": category_id}).scalar_one_or_none()
        if current is None:
            raise HTTPException(404, "La inscripción no está asignada a un grupo de esta categoría.")
        if int(current) == group_id:
            return _group_details(db, [group_id])[group_id]
        count = int(db.execute(text("""
          SELECT COUNT(*) FROM dbo.TournamentGroupRegistrations WITH (UPDLOCK,HOLDLOCK)
          WHERE TournamentGroupId=:group
        """), {"group": group_id}).scalar_one())
        if count >= int(target["MaxTeams"]):
            raise HTTPException(409, "El grupo de destino alcanzó su capacidad máxima de equipos.")
        db.execute(text("DELETE dbo.TournamentGroupRegistrations WHERE RegistrationId=:registration"),
                   {"registration": registration_id})
        db.execute(text("""
          INSERT dbo.TournamentGroupRegistrations(TournamentGroupId,RegistrationId,AssignedByUserId)
          VALUES(:group,:registration,:actor)
        """), {"group": group_id, "registration": registration_id, "actor": user["user_id"]})
        db.commit()
        return {"moved": True, "registration_id": registration_id,
                "from_group_id": int(current), "to_group_id": group_id}
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "No se pudo mover la inscripción; comprueba la capacidad y el torneo.") from exc
    except Exception:
        db.rollback()
        raise


@router.delete("/{event_id}/categories/{category_id}/tournament-groups/{group_id}/registrations/{registration_id}", status_code=204)
def remove_registration(event_id: int, category_id: int, group_id: int, registration_id: int,
                        user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    _validate_event_category(db, event_id, category_id)
    if _tournament_started(db, event_id, category_id, lock=True):
        raise HTTPException(409, "El torneo ya inició; no se pueden cambiar las asignaciones.")
    result = db.execute(text("""
      DELETE a FROM dbo.TournamentGroupRegistrations a
      JOIN dbo.TournamentGroups g ON g.TournamentGroupId=a.TournamentGroupId
      WHERE a.TournamentGroupId=:group AND a.RegistrationId=:registration
        AND g.EventId=:event AND g.CategoryId=:category
    """), {"group": group_id, "registration": registration_id,
          "event": event_id, "category": category_id})
    if not result.rowcount:
        db.rollback()
        raise HTTPException(404, "La inscripción no está asignada a este grupo.")
    db.commit()
    return Response(status_code=204)
