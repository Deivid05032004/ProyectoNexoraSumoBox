"""Competition lifecycle, append-only scoring, public leaderboard and live feed."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.dependencies.auth import require_roles
from database import SessionLocal, get_db

router = APIRouter(prefix="/api/v1", tags=["Competencias y puntuaciones"])
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
    try:
        match_id = db.execute(text("""
          INSERT dbo.CompetitionMatches(RoundId,MatchNumber) OUTPUT INSERTED.MatchId
          VALUES(:round,:number)
        """), {"round": payload.round_id, "number": payload.match_number}).scalar_one()
        for team_id in team_ids:
            db.execute(text("INSERT dbo.CompetitionMatchTeams(MatchId,TeamId) VALUES(:match,:team)"),
                       {"match": match_id, "team": team_id})
        db.commit()
        return {"match_id": match_id, "event_id": event_id, "round_id": payload.round_id,
                "match_number": payload.match_number, "team_ids": team_ids}
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
