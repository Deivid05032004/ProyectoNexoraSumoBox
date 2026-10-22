"""Competition lifecycle, append-only scoring, public leaderboard and live feed."""
import asyncio
from uuid import UUID, uuid4

from fastapi import (APIRouter, Depends, Header, HTTPException, Query,
                     WebSocket, WebSocketDisconnect)
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.dependencies.auth import require_roles
from app.schemas.combat import CurrentCombatUpdate
from app.services.combat_live import live_combat_connections
from database import SessionLocal, get_db

router = APIRouter(prefix="/api/v1", tags=["Competencias y puntuaciones"])
live_router = APIRouter(tags=["Combate en tiempo real"])
STAFF = ("ADMIN", "EVENT_MANAGER")
TRANSITIONS = {"DRAFT": {"SCHEDULED", "CANCELLED"}, "SCHEDULED": {"LIVE", "CANCELLED"},
               "LIVE": {"PAUSED", "FINISHED", "CANCELLED"}, "PAUSED": {"LIVE", "FINISHED", "CANCELLED"},
               "FINISHED": set(), "CANCELLED": set()}


def can_transition(previous: str, target: str) -> bool:
    return target == previous or target in TRANSITIONS.get(previous, set())


def rank_rows(rows: list[dict]) -> list[dict]:
    previous_category, previous_points, rank = None, None, 0
    for item in rows:
        if item["category_id"] != previous_category:
            previous_category, previous_points, rank = item["category_id"], None, 0
        if item["points"] != previous_points:
            rank += 1
            previous_points = item["points"]
        item["rank"] = rank
    return rows


class StateChange(BaseModel):
    status: str = Field(pattern="^(DRAFT|SCHEDULED|LIVE|PAUSED|FINISHED|CANCELLED)$")
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def non_blank_reason(cls, value):
        if value is not None and not value.strip():
            raise ValueError("El motivo no puede estar vacío.")
        return value.strip() if value is not None else None


class ScoreInput(BaseModel):
    category_id: int = Field(gt=0)
    team_id: int = Field(gt=0)
    points_delta: int = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=1, max_length=500)
    round_id: int | None = Field(default=None, gt=0)
    match_id: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def non_blank_reason(cls, value):
        if not value.strip():
            raise ValueError("El motivo no puede estar vacío.")
        return value.strip()


class RoundInput(BaseModel):
    category_id: int = Field(gt=0)
    round_number: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)


class MatchInput(BaseModel):
    round_id: int = Field(gt=0)
    match_number: int = Field(gt=0)
    team_ids: list[int] = Field(min_length=2, max_length=8)
    robot_ids: list[int] | None = Field(default=None, min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_robot_slots(self):
        if self.robot_ids is not None and len(self.robot_ids) != len(self.team_ids):
            raise ValueError("robot_ids debe corresponder en orden a team_ids.")
        if self.robot_ids is not None and len(set(self.robot_ids)) != len(self.robot_ids):
            raise ValueError("No repita robots en un enfrentamiento.")
        return self


def _leaderboard(db: Session, event_id: int, category_id: int | None):
    rows = db.execute(text("""
      SELECT r.CategoryId AS category_id,c.Name AS category,t.TeamId AS team_id,t.Name AS team,
        COALESCE(SUM(CONVERT(BIGINT,se.PointsDelta)),0) AS points,MAX(se.CreatedAt) AS updated_at
      FROM dbo.Registrations r JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
      JOIN dbo.Categories c ON c.CategoryId=r.CategoryId JOIN dbo.Teams t ON t.TeamId=r.TeamId
      LEFT JOIN dbo.ScoreEntries se ON se.EventId=r.EventId AND se.CategoryId=r.CategoryId AND se.TeamId=r.TeamId
      WHERE r.EventId=:event AND (:category IS NULL OR r.CategoryId=:category)
      GROUP BY r.CategoryId,c.Name,t.TeamId,t.Name
      ORDER BY r.CategoryId,points DESC,t.Name,t.TeamId
    """), {"event": event_id, "category": category_id}).mappings().all()
    result = [dict(row) for row in rows]
    for row in result:
        row["team"] = decrypt_text(row["team"])
    return result


def _broadcast_active_combat_if(db: Session, *, event_id: int | None = None,
                                match_id: int | None = None) -> None:
    current = db.execute(text("""
      SELECT ac.MatchId,cr.EventId FROM dbo.ActiveCombat ac
      JOIN dbo.CompetitionMatches m ON m.MatchId=ac.MatchId
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      WHERE ac.ActiveCombatId=1
    """)).first()
    if current and ((match_id is not None and current.MatchId == match_id)
                    or (event_id is not None and current.EventId == event_id)):
        live_combat_connections.broadcast_from_sync_route(_current_combat_snapshot(db))


@router.post("/events/{event_id}/rounds", status_code=201)
def create_round(event_id: int, payload: RoundInput,
                 user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    if not db.execute(text("SELECT 1 FROM dbo.Categories WHERE CategoryId=:id AND IsActive=1"),
                      {"id": payload.category_id}).first():
        raise HTTPException(422, "Categoría inexistente o inactiva.")
    try:
        row = db.execute(text("""
          INSERT dbo.CompetitionRounds(EventId,CategoryId,RoundNumber,Name)
          OUTPUT INSERTED.RoundId AS id,INSERTED.EventId AS event_id,INSERTED.CategoryId AS category_id,
            INSERTED.RoundNumber AS round_number,INSERTED.Name AS name,INSERTED.RoundStatus AS status
          VALUES(:event,:category,:number,:name)
        """), {"event": event_id, "category": payload.category_id,
              "number": payload.round_number, "name": payload.name.strip()}).mappings().one()
        db.commit()
        return dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe esa ronda para el evento y categoría.")


@router.post("/events/{event_id}/matches", status_code=201)
def create_match(event_id: int, payload: MatchInput,
                 user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    team_ids = list(dict.fromkeys(payload.team_ids))
    if len(team_ids) != len(payload.team_ids):
        raise HTTPException(422, "No repitas equipos en un enfrentamiento.")
    round_category = db.execute(text("""
      SELECT CategoryId FROM dbo.CompetitionRounds WHERE EventId=:event AND RoundId=:round
    """), {"event": event_id, "round": payload.round_id}).scalar_one_or_none()
    if round_category is None:
        raise HTTPException(404, "Ronda no encontrada en esta competencia.")
    for team_id in team_ids:
        if not db.execute(text("""
          SELECT 1 FROM dbo.Registrations r JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
          WHERE r.EventId=:event AND r.CategoryId=:category AND r.TeamId=:team AND s.Code='APPROVED'
        """), {"event": event_id, "category": round_category, "team": team_id}).first():
            raise HTTPException(422, "Todos los equipos deben estar aprobados para esta ronda.")
    chosen_robots = []
    for index, team_id in enumerate(team_ids):
        eligible_robots = db.execute(text("""
          SELECT DISTINCT r.RobotId FROM dbo.Registrations r
          JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId AND s.Code='APPROVED'
          WHERE r.EventId=:event AND r.CategoryId=:category AND r.TeamId=:team
          ORDER BY r.RobotId
        """), {"event": event_id, "category": round_category, "team": team_id}).scalars().all()
        if not eligible_robots:
            raise HTTPException(422, "Todos los equipos deben tener un robot aprobado en esta categoría y competencia.")
        robot_id = payload.robot_ids[index] if payload.robot_ids is not None else (
            eligible_robots[0] if len(eligible_robots) == 1 else None)
        if robot_id is None:
            raise HTTPException(422, "Seleccione un robot para cada equipo cuando tenga varias inscripciones aprobadas.")
        if robot_id not in eligible_robots:
            raise HTTPException(422, "El robot seleccionado no está aprobado para ese equipo, evento y categoría.")
        chosen_robots.append(robot_id)
    try:
        match_id = db.execute(text("""
          INSERT dbo.CompetitionMatches(RoundId,MatchNumber) OUTPUT INSERTED.MatchId
          VALUES(:round,:number)
        """), {"round": payload.round_id, "number": payload.match_number}).scalar_one()
        for position, (team_id, robot_id) in enumerate(zip(team_ids, chosen_robots), start=1):
            db.execute(text("""
                INSERT dbo.CompetitionMatchTeams(MatchId,TeamId,RobotId,TeamPosition)
                VALUES(:match,:team,:robot,:position)
            """), {"match": match_id, "team": team_id, "robot": robot_id,
                  "position": position})
        db.commit()
        return {"match_id": match_id, "event_id": event_id, "round_id": payload.round_id,
                "match_number": payload.match_number, "team_ids": team_ids,
                "robot_ids": chosen_robots}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe ese número de enfrentamiento en la ronda.")


@router.patch("/events/{event_id}/competition-status")
def set_competition_status(event_id: int, payload: StateChange,
                           user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    row = db.execute(text("SELECT CompetitionStatus FROM dbo.Events WITH (UPDLOCK,HOLDLOCK) WHERE EventId=:id"),
                     {"id": event_id}).first()
    if row is None:
        raise HTTPException(404, "Evento no encontrado.")
    previous = row[0]
    if not can_transition(previous, payload.status):
        raise HTTPException(409, f"Transición no permitida: {previous} → {payload.status}.")
    db.execute(text("UPDATE dbo.Events SET CompetitionStatus=:status WHERE EventId=:id"),
               {"status": payload.status, "id": event_id})
    if previous != payload.status:
        db.execute(text("""
          INSERT dbo.CompetitionEventStatusHistory(EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
          VALUES(:event,:previous,:next,:actor,:reason)
        """), {"event": event_id, "previous": previous, "next": payload.status,
              "actor": user["user_id"], "reason": payload.reason.strip() if payload.reason else None})
    db.commit()
    _broadcast_active_combat_if(db, event_id=event_id)
    return {"event_id": event_id, "previous_status": previous, "status": payload.status}


@router.post("/events/{event_id}/scores", status_code=201)
def add_score(event_id: int, payload: ScoreInput,
              idempotency_key: UUID = Header(alias="Idempotency-Key"),
              user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    key = idempotency_key
    existing = db.execute(text("SELECT ScoreEntryId FROM dbo.ScoreEntries WHERE IdempotencyKey=:key"),
                          {"key": key}).scalar_one_or_none()
    if existing:
        return {"score_entry_id": existing, "idempotency_key": str(key), "replayed": True}
    try:
        state = db.execute(text("SELECT CompetitionStatus FROM dbo.Events WITH (UPDLOCK,HOLDLOCK) WHERE EventId=:id"),
                           {"id": event_id}).scalar_one_or_none()
        if state is None:
            raise HTTPException(404, "Evento no encontrado.")
        if state != "LIVE":
            raise HTTPException(409, "Solo se puede puntuar una competencia en curso.")
        eligible = db.execute(text("""
          SELECT 1 FROM dbo.Registrations r JOIN dbo.RegistrationStatuses s ON s.StatusId=r.StatusId
          WHERE r.EventId=:event AND r.CategoryId=:category AND r.TeamId=:team AND s.Code='APPROVED'
        """), {"event": event_id, "category": payload.category_id, "team": payload.team_id}).first()
        if not eligible:
            raise HTTPException(422, "El equipo no está habilitado en esta categoría y competencia.")
        if payload.round_id and not db.execute(text("""
          SELECT 1 FROM dbo.CompetitionRounds WHERE RoundId=:round AND EventId=:event AND CategoryId=:category
        """), {"round": payload.round_id, "event": event_id, "category": payload.category_id}).first():
            raise HTTPException(422, "La ronda no corresponde a la competencia y categoría.")
        if payload.match_id and (not payload.round_id or not db.execute(text("""
          SELECT 1 FROM dbo.CompetitionMatches m JOIN dbo.CompetitionMatchTeams mt ON mt.MatchId=m.MatchId
          WHERE m.MatchId=:match AND m.RoundId=:round AND mt.TeamId=:team
        """), {"match": payload.match_id, "round": payload.round_id, "team": payload.team_id}).first()):
            raise HTTPException(422, "El enfrentamiento no incluye al equipo indicado.")
        total = int(db.execute(text("""
          SELECT COALESCE(SUM(CONVERT(BIGINT,PointsDelta)),0) FROM dbo.ScoreEntries WITH (UPDLOCK,HOLDLOCK)
          WHERE EventId=:event AND CategoryId=:category AND TeamId=:team
        """), {"event": event_id, "category": payload.category_id, "team": payload.team_id}).scalar_one())
        if total + payload.points_delta < 0:
            raise HTTPException(422, "El ajuste no puede dejar una puntuación negativa.")
        entry_id = db.execute(text("""
          INSERT dbo.ScoreEntries(EventId,CategoryId,TeamId,RoundId,MatchId,PointsDelta,Reason,IdempotencyKey,CreatedByUserId)
          OUTPUT INSERTED.ScoreEntryId
          VALUES(:event,:category,:team,:round,:match,:delta,:reason,:key,:actor)
        """), {"event": event_id, "category": payload.category_id, "team": payload.team_id,
              "round": payload.round_id, "match": payload.match_id, "delta": payload.points_delta,
              "reason": payload.reason.strip(), "key": key, "actor": user["user_id"]}).scalar_one()
        db.commit()
        if payload.match_id is not None:
            _broadcast_active_combat_if(db, match_id=payload.match_id)
        return {"score_entry_id": entry_id, "event_id": event_id, "category_id": payload.category_id,
                "team_id": payload.team_id, "points_delta": payload.points_delta,
                "total_points": total + payload.points_delta, "idempotency_key": str(key)}
    except IntegrityError:
        db.rollback()
        existing = db.execute(text("SELECT ScoreEntryId FROM dbo.ScoreEntries WHERE IdempotencyKey=:key"),
                              {"key": key}).scalar_one_or_none()
        if existing:
            return {"score_entry_id": existing, "idempotency_key": str(key), "replayed": True}
        raise HTTPException(409, "No se pudo registrar la puntuación por un conflicto de integridad.")
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get("/events/{event_id}/leaderboard")
def leaderboard(event_id: int, category_id: int | None = Query(default=None, gt=0), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    rows = _leaderboard(db, event_id, category_id)
    # Dense rank deliberately preserves ties; no sporting tie-break is assumed.
    rank_rows(rows)
    return {"event_id": event_id, "items": rows}


@router.get("/events/{event_id}/scores/history")
def score_history(event_id: int, category_id: int | None = Query(default=None, gt=0),
                  team_id: int | None = Query(default=None, gt=0), page: int = Query(1, ge=1),
                  limit: int = Query(50, ge=1, le=100),
                  db: Session = Depends(get_db)):
    rows = db.execute(text("""
      SELECT ScoreEntryId AS id,CategoryId AS category_id,TeamId AS team_id,RoundId AS round_id,
        MatchId AS match_id,PointsDelta AS points_delta,
        CreatedAt AS created_at FROM dbo.ScoreEntries
      WHERE EventId=:event AND (:category IS NULL OR CategoryId=:category) AND (:team IS NULL OR TeamId=:team)
      ORDER BY ScoreEntryId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"event": event_id, "category": category_id, "team": team_id,
          "offset": (page-1)*limit, "limit": limit}).mappings().all()
    total = db.execute(text("""SELECT COUNT_BIG(*) FROM dbo.ScoreEntries WHERE EventId=:event
      AND (:category IS NULL OR CategoryId=:category) AND (:team IS NULL OR TeamId=:team)"""),
      {"event": event_id, "category": category_id, "team": team_id}).scalar_one()
    return {"items": [dict(row) for row in rows], "page": page, "page_size": limit, "total": int(total)}


@router.get("/events/{event_id}/scores/audit")
def score_audit(event_id: int, category_id: int | None = Query(default=None, gt=0),
                team_id: int | None = Query(default=None, gt=0), page: int = Query(1, ge=1),
                limit: int = Query(50, ge=1, le=100), user=Depends(require_roles(*STAFF)),
                db: Session = Depends(get_db)):
    rows = db.execute(text("""
      SELECT ScoreEntryId AS id,CategoryId AS category_id,TeamId AS team_id,RoundId AS round_id,
        MatchId AS match_id,PointsDelta AS points_delta,Reason AS reason,CreatedByUserId AS actor_user_id,
        CreatedAt AS created_at FROM dbo.ScoreEntries
      WHERE EventId=:event AND (:category IS NULL OR CategoryId=:category) AND (:team IS NULL OR TeamId=:team)
      ORDER BY ScoreEntryId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"event": event_id, "category": category_id, "team": team_id,
          "offset": (page-1)*limit, "limit": limit}).mappings().all()
    total = int(db.execute(text("""SELECT COUNT_BIG(*) FROM dbo.ScoreEntries WHERE EventId=:event
      AND (:category IS NULL OR CategoryId=:category) AND (:team IS NULL OR TeamId=:team)"""),
      {"event": event_id, "category": category_id, "team": team_id}).scalar_one())
    return {"items": [dict(row) for row in rows], "page": page, "page_size": limit, "total": total}


@router.get("/events/{event_id}/competition-status/history")
def competition_status_history(event_id: int, page: int = Query(1, ge=1),
                               limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    total = int(db.execute(text("SELECT COUNT_BIG(*) FROM dbo.CompetitionEventStatusHistory WHERE EventId=:id"),
                           {"id": event_id}).scalar_one())
    rows = db.execute(text("""
      SELECT HistoryId AS id,PreviousStatus AS previous_status,NewStatus AS new_status,
        Reason AS reason,ChangedAt AS changed_at FROM dbo.CompetitionEventStatusHistory
      WHERE EventId=:id ORDER BY HistoryId DESC OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"id": event_id, "offset": (page-1)*limit, "limit": limit}).mappings().all()
    return {"items": [dict(row) for row in rows], "page": page, "page_size": limit, "total": total}


@router.get("/events/{event_id}/rounds")
def list_rounds(event_id: int, category_id: int | None = Query(default=None, gt=0),
                page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100),
                db: Session = Depends(get_db)):
    rows = db.execute(text("""
      SELECT RoundId AS id,CategoryId AS category_id,RoundNumber AS round_number,
        Name AS name,RoundStatus AS status,CreatedAt AS created_at
      FROM dbo.CompetitionRounds WHERE EventId=:event AND (:category IS NULL OR CategoryId=:category)
      ORDER BY CategoryId,RoundNumber OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"event": event_id, "category": category_id,
          "offset": (page-1)*limit, "limit": limit}).mappings().all()
    total = int(db.execute(text("""SELECT COUNT_BIG(*) FROM dbo.CompetitionRounds
      WHERE EventId=:event AND (:category IS NULL OR CategoryId=:category)"""),
      {"event": event_id, "category": category_id}).scalar_one())
    return {"items": [dict(row) for row in rows], "page": page, "page_size": limit, "total": total}


@router.get("/events/{event_id}/matches")
def list_matches(event_id: int, round_id: int | None = Query(default=None, gt=0),
                 page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100),
                 db: Session = Depends(get_db)):
    rows = db.execute(text("""
      SELECT m.MatchId AS id,m.RoundId AS round_id,m.MatchNumber AS match_number,
        m.MatchStatus AS status,rt.TeamId AS team_id,t.Name AS team_name
      FROM dbo.CompetitionMatches m JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      JOIN dbo.CompetitionMatchTeams rt ON rt.MatchId=m.MatchId JOIN dbo.Teams t ON t.TeamId=rt.TeamId
      WHERE cr.EventId=:event AND (:round IS NULL OR m.RoundId=:round)
      ORDER BY cr.CategoryId,cr.RoundNumber,m.MatchNumber,t.TeamId
      OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """), {"event": event_id, "round": round_id,
          "offset": (page-1)*limit, "limit": limit}).mappings().all()
    total = int(db.execute(text("""SELECT COUNT_BIG(*) FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE r.EventId=:event AND (:round IS NULL OR m.RoundId=:round)"""),
      {"event": event_id, "round": round_id}).scalar_one())
    result = [dict(row) for row in rows]
    for row in result:
        row["team_name"] = decrypt_text(row["team_name"])
    return {"items": result, "page": page, "page_size": limit, "total": total}


def _current_combat_snapshot(db: Session) -> dict:
    rows = db.execute(text("""
      SELECT m.MatchId AS match_id,m.MatchNumber AS match_number,m.MatchStatus AS match_status,
        m.PublicDetails AS details,
        e.EventId AS event_id,e.Name AS event_name,e.CompetitionStatus AS event_status,
        cr.RoundId AS round_id,cr.CategoryId AS category_id,c.Name AS category_name,
        mt.TeamId AS team_id,t.Name AS team_name,i.Name AS institution_name,
        picked_robot.RobotId AS robot_id,picked_robot.RobotName AS robot_name,
        COALESCE(score.TotalPoints,0) AS points,ac.UpdatedAt AS updated_at
      FROM dbo.ActiveCombat ac
      JOIN dbo.CompetitionMatches m ON m.MatchId=ac.MatchId
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      JOIN dbo.Events e ON e.EventId=cr.EventId
      JOIN dbo.Categories c ON c.CategoryId=cr.CategoryId
      JOIN dbo.CompetitionMatchTeams mt ON mt.MatchId=m.MatchId
      JOIN dbo.Teams t ON t.TeamId=mt.TeamId
      JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      OUTER APPLY (
        SELECT TOP (1) r.RobotId,rb.Name AS RobotName
        FROM dbo.Registrations r
        JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
        JOIN dbo.Robots rb ON rb.RobotId=r.RobotId
        WHERE r.EventId=cr.EventId AND r.CategoryId=cr.CategoryId AND r.TeamId=mt.TeamId
          AND (mt.RobotId IS NULL OR mt.RobotId=r.RobotId)
        ORDER BY CASE WHEN mt.RobotId IS NULL THEN 1 ELSE 0 END,r.RegisteredAt,r.RobotId
      ) picked_robot
      OUTER APPLY (
        SELECT SUM(CONVERT(BIGINT,se.PointsDelta)) AS TotalPoints
        FROM dbo.ScoreEntries se WHERE se.MatchId=m.MatchId AND se.TeamId=mt.TeamId
      ) score
      WHERE ac.ActiveCombatId=1
      ORDER BY CASE WHEN mt.TeamPosition IS NULL THEN 255 ELSE mt.TeamPosition END,mt.TeamId
    """)).mappings().all()
    if not rows:
        return {"active": False, "id": None, "id_combate": None, "match_id": None,
                "event_id": None, "event_name": None, "round_id": None,
                "robot_a": None, "institucion_a": None, "equipo_a": None,
                "team_id_a": None, "robot_id_a": None, "puntaje_a": 0,
                "robot_b": None, "institucion_b": None, "equipo_b": None,
                "team_id_b": None, "robot_id_b": None, "puntaje_b": 0,
                "estado": "Sin combate activo", "estado_code": "SIN_COMBATE_ACTIVO",
                "torneo": "UTA SUMO ROBOTICS CUP 2026", "category_id": None,
                "categoria": None, "robotA": {"nombre": "Por definir", "institucion": "Sin asignar", "puntos": 0},
                "robotB": {"nombre": "Por definir", "institucion": "Sin asignar", "puntos": 0},
                "ganador": "No definido", "detalles": "", "updated_at": None,
                "ultimaActualizacion": "--:--"}
    if len(rows) != 2:
        raise HTTPException(503, "El combate actual debe tener exactamente dos equipos.")
    first, second = rows
    event_status = first["event_status"]
    match_status = first["match_status"]
    if match_status == "FINISHED" or event_status == "FINISHED":
        display_status = "FINALIZADO"
    elif match_status == "CANCELLED" or event_status == "CANCELLED":
        display_status = "CANCELADO"
    elif event_status == "PAUSED" and match_status == "LIVE":
        display_status = "PAUSADO"
    elif match_status == "LIVE":
        display_status = "EN_VIVO"
    else:
        display_status = "PROGRAMADO"
    status_labels = {
        "PROGRAMADO": "Programado", "EN_VIVO": "En combate",
        "PAUSADO": "Pausado", "FINALIZADO": "Finalizado",
        "CANCELADO": "Cancelado",
    }
    first_points = int(first["points"] or 0)
    second_points = int(second["points"] or 0)
    if display_status != "FINALIZADO" or first_points == second_points:
        winner = "Empate" if display_status == "FINALIZADO" and first_points == second_points else "No definido"
    else:
        winner = decrypt_text(first["robot_name"] if first_points > second_points else second["robot_name"])
    updated_at = first["updated_at"]
    robot_a = {"nombre": decrypt_text(first["robot_name"]),
               "institucion": first["institution_name"], "puntos": first_points}
    robot_b = {"nombre": decrypt_text(second["robot_name"]),
               "institucion": second["institution_name"], "puntos": second_points}
    return {
        "active": display_status in ("PROGRAMADO", "EN_VIVO", "PAUSADO"),
        "id": f"COMB-{first['match_number']:02d}",
        "id_combate": f"COMB-{first['match_number']:02d}",
        "match_id": int(first["match_id"]), "event_id": first["event_id"],
        "event_name": first["event_name"], "torneo": first["event_name"],
        "round_id": first["round_id"],
        "robot_a": decrypt_text(first["robot_name"]),
        "institucion_a": first["institution_name"],
        "equipo_a": decrypt_text(first["team_name"]),
        "team_id_a": first["team_id"], "robot_id_a": first["robot_id"],
        "puntaje_a": first_points,
        "robot_b": decrypt_text(second["robot_name"]),
        "institucion_b": second["institution_name"],
        "equipo_b": decrypt_text(second["team_name"]),
        "team_id_b": second["team_id"], "robot_id_b": second["robot_id"],
        "puntaje_b": second_points,
        "estado": status_labels[display_status], "estado_code": display_status,
        "category_id": first["category_id"],
        "categoria": first["category_name"],
        "robotA": robot_a, "robotB": robot_b, "ganador": winner,
        "detalles": first["details"] or "",
        "updated_at": updated_at.isoformat() if updated_at else None,
        "ultimaActualizacion": updated_at.strftime("%H:%M") if updated_at else "--:--",
    }


def _load_current_combat_snapshot() -> dict:
    db = SessionLocal()
    try:
        return _current_combat_snapshot(db)
    finally:
        db.close()


def _write_event_status(db: Session, event_id: int, target: str, actor_id: int,
                        reason: str | None) -> None:
    current = db.execute(text("""
      SELECT CompetitionStatus FROM dbo.Events WITH (UPDLOCK,HOLDLOCK) WHERE EventId=:event
    """), {"event": event_id}).scalar_one_or_none()
    if current is None:
        raise HTTPException(404, "Evento no encontrado.")
    targets = [target]
    if current == "DRAFT" and target == "LIVE":
        targets = ["SCHEDULED", "LIVE"]
    previous = current
    for next_status in targets:
        if not can_transition(previous, next_status):
            raise HTTPException(409, f"Transición de evento no permitida: {previous} → {next_status}.")
        if previous != next_status:
            db.execute(text("UPDATE dbo.Events SET CompetitionStatus=:status WHERE EventId=:event"),
                       {"status": next_status, "event": event_id})
            db.execute(text("""
              INSERT dbo.CompetitionEventStatusHistory
                (EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
              VALUES(:event,:previous,:next,:actor,:reason)
            """), {"event": event_id, "previous": previous, "next": next_status,
                  "actor": actor_id, "reason": reason})
        previous = next_status


def _apply_current_combat_update(payload: CurrentCombatUpdate, user: dict) -> dict:
    db = SessionLocal()
    try:
        current_match_id = db.execute(text("""
          SELECT MatchId FROM dbo.ActiveCombat WITH (UPDLOCK,HOLDLOCK) WHERE ActiveCombatId=1
        """)).scalar_one_or_none()
        match_id = payload.match_id or current_match_id
        if match_id is None:
            raise HTTPException(409, "Selecciona un combate programado antes de actualizar el marcador.")
        if current_match_id is not None and payload.match_id is not None and current_match_id != payload.match_id:
            old_status = db.execute(text("SELECT MatchStatus FROM dbo.CompetitionMatches WHERE MatchId=:id"),
                                    {"id": current_match_id}).scalar_one_or_none()
            if old_status == "LIVE":
                raise HTTPException(409, "Finaliza o cancela el combate actual antes de seleccionar otro.")

        match = db.execute(text("""
          SELECT m.MatchId AS match_id,m.MatchNumber AS match_number,m.MatchStatus AS match_status,
            m.PublicDetails AS public_details,
            cr.EventId AS event_id,cr.CategoryId AS category_id,e.CompetitionStatus AS event_status
          FROM dbo.CompetitionMatches m WITH (UPDLOCK,ROWLOCK)
          JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
          JOIN dbo.Events e ON e.EventId=cr.EventId
          WHERE m.MatchId=:id
        """), {"id": match_id}).mappings().first()
        if match is None:
            raise HTTPException(404, "Combate no encontrado.")
        if match["event_status"] in ("FINISHED", "CANCELLED"):
            raise HTTPException(409, "El evento ya está cerrado.")
        teams = db.execute(text("""
          SELECT TeamId FROM dbo.CompetitionMatchTeams WHERE MatchId=:match
          ORDER BY CASE WHEN TeamPosition IS NULL THEN 255 ELSE TeamPosition END,TeamId
        """), {"match": match_id}).scalars().all()
        if len(teams) != 2:
            raise HTTPException(422, "El combate actual requiere exactamente dos equipos.")
        if (current_match_id != match_id and match["match_status"] not in ("SCHEDULED", "LIVE")):
            raise HTTPException(409, "Solo se puede seleccionar un combate programado o en curso.")

        previous_match_status = match["match_status"]
        effective_match_status = previous_match_status
        if payload.status is not None:
            allowed = {
                "SCHEDULED": {"PROGRAMADO", "EN_VIVO", "CANCELADO"},
                "LIVE": {"EN_VIVO", "PAUSADO", "FINALIZADO", "CANCELADO"},
                "FINISHED": set(), "CANCELLED": set(),
            }
            if payload.status not in allowed.get(previous_match_status, set()):
                raise HTTPException(409, f"Transición de combate no permitida desde {previous_match_status}.")
            effective_match_status = {
                "PROGRAMADO": "SCHEDULED", "EN_VIVO": "LIVE", "PAUSADO": "LIVE",
                "FINALIZADO": "FINISHED", "CANCELADO": "CANCELLED",
            }[payload.status]
            if payload.status == "EN_VIVO":
                _write_event_status(db, match["event_id"], "LIVE", user["user_id"], payload.reason)
            elif payload.status == "PAUSADO":
                _write_event_status(db, match["event_id"], "PAUSED", user["user_id"], payload.reason)
            db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus=:status WHERE MatchId=:id"),
                       {"status": effective_match_status, "id": match_id})
        details_changed = ("details" in payload.model_fields_set
                           and payload.details != match["public_details"])
        if details_changed:
            db.execute(text("UPDATE dbo.CompetitionMatches SET PublicDetails=:details WHERE MatchId=:id"),
                       {"details": payload.details, "id": match_id})
        elif payload.score_a is not None and (previous_match_status != "LIVE"
                                               or match["event_status"] not in ("LIVE", "PAUSED")):
            raise HTTPException(409, "Solo se puede ajustar el marcador de un combate en curso o pausado.")

        current_points_rows = db.execute(text("""
          SELECT TeamId,COALESCE(SUM(CONVERT(BIGINT,PointsDelta)),0) AS Points
          FROM dbo.ScoreEntries WHERE MatchId=:match AND TeamId IN (:team_a,:team_b)
          GROUP BY TeamId
        """), {"match": match_id, "team_a": teams[0], "team_b": teams[1]}).all()
        points = {team_id: 0 for team_id in teams}
        points.update({int(team_id): int(value) for team_id, value in current_points_rows})
        score_changed = False
        if payload.score_a is not None:
            for team_id, target_score in zip(teams, (payload.score_a, payload.score_b)):
                delta = target_score - points[team_id]
                if delta:
                    db.execute(text("""
                      INSERT dbo.ScoreEntries
                        (EventId,CategoryId,TeamId,RoundId,MatchId,PointsDelta,Reason,IdempotencyKey,CreatedByUserId)
                      VALUES(:event,:category,:team,:round,:match,:delta,:reason,:key,:actor)
                    """), {"event": match["event_id"], "category": match["category_id"],
                          "team": team_id, "round": db.execute(text(
                              "SELECT RoundId FROM dbo.CompetitionMatches WHERE MatchId=:id"),
                              {"id": match_id}).scalar_one(), "match": match_id,
                          "delta": delta, "reason": payload.reason,
                          "key": uuid4(), "actor": user["user_id"]})
                    score_changed = True

        pointer_changed = current_match_id != match_id
        if pointer_changed:
            if current_match_id is None:
                db.execute(text("""
                  INSERT dbo.ActiveCombat(ActiveCombatId,MatchId,UpdatedByUserId)
                  VALUES(1,:match,:actor)
                """), {"match": match_id, "actor": user["user_id"]})
            else:
                db.execute(text("""
                  UPDATE dbo.ActiveCombat SET MatchId=:match,UpdatedByUserId=:actor,
                    UpdatedAt=SYSUTCDATETIME() WHERE ActiveCombatId=1
                """), {"match": match_id, "actor": user["user_id"]})
            db.execute(text("""
              INSERT dbo.ActiveCombatHistory
                (PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
              VALUES(:previous,:next,:actor,:action,:reason)
            """), {"previous": current_match_id, "next": match_id, "actor": user["user_id"],
                  "action": "SELECTED" if current_match_id is None else "REPLACED",
                  "reason": payload.reason})
        elif payload.status is not None or score_changed or details_changed:
            db.execute(text("""
              UPDATE dbo.ActiveCombat SET UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
              WHERE ActiveCombatId=1 AND MatchId=:match
            """), {"actor": user["user_id"], "match": match_id})
            if payload.status is not None:
                action = "STATUS_CHANGED"
            elif score_changed:
                action = "SCORE_CHANGED"
            elif details_changed:
                action = "DETAILS_CHANGED"
            else:
                action = None
            if action:
                db.execute(text("""
                  INSERT dbo.ActiveCombatHistory
                    (PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
                  VALUES(:match,:match,:actor,:action,:reason)
                """), {"match": match_id, "actor": user["user_id"], "action": action,
                      "reason": payload.reason})

        if pointer_changed:
            for action, changed in (("STATUS_CHANGED", payload.status is not None),
                                    ("SCORE_CHANGED", score_changed),
                                    ("DETAILS_CHANGED", details_changed)):
                if changed:
                    db.execute(text("""
                      INSERT dbo.ActiveCombatHistory
                        (PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
                      VALUES(:match,:match,:actor,:action,:reason)
                    """), {"match": match_id, "actor": user["user_id"],
                          "action": action, "reason": payload.reason})

        snapshot = _current_combat_snapshot(db)
        db.commit()
        return snapshot
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo actualizar el combate por un conflicto de integridad.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/competition/combate-actual")
def get_current_combat(db: Session = Depends(get_db)):
    return _current_combat_snapshot(db)


@router.put("/competition/combate-actual")
async def update_current_combat(payload: CurrentCombatUpdate,
                                user=Depends(require_roles(*STAFF))):
    snapshot = await asyncio.to_thread(_apply_current_combat_update, payload, user)
    await live_combat_connections.broadcast(snapshot)
    return snapshot


@live_router.websocket("/ws/combate-actual")
async def live_current_combat(websocket: WebSocket):
    try:
        await live_combat_connections.connect(websocket, _load_current_combat_snapshot)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return
    except RuntimeError:
        return
    finally:
        await live_combat_connections.disconnect(websocket)


def _load_live_snapshot(event_id: int):
    db = SessionLocal()
    try:
        state = db.execute(text("SELECT CompetitionStatus FROM dbo.Events WHERE EventId=:id"),
                           {"id": event_id}).scalar_one_or_none()
        items = _leaderboard(db, event_id, None)
        return {"event_id": event_id, "status": state,
                "items": [{k: v for k, v in item.items() if k != "updated_at"} for item in items]}
    finally:
        db.close()


@router.websocket("/events/{event_id}/live")
async def live_results(websocket: WebSocket, event_id: int):
    # Public stream exposes standings only, never PII or payment data.
    db = SessionLocal()
    try:
        exists = db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first()
        if not exists:
            await websocket.close(code=4404)
            return
    finally:
        db.close()
    await websocket.accept()
    last_snapshot = None
    try:
        while True:
            snapshot = await asyncio.to_thread(_load_live_snapshot, event_id)
            if snapshot != last_snapshot:
                await websocket.send_json(snapshot)
                last_snapshot = snapshot
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=2)
                if message["type"] == "websocket.disconnect":
                    return
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
