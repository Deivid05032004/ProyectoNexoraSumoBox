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


class MatchTimerConfig(BaseModel):
    enabled: bool
    duration_seconds: int = Field(ge=1, le=5999)
    direction: str = Field(default="DOWN", pattern="^(UP|DOWN)$")


class TournamentTeamAssignment(BaseModel):
    team_id: int = Field(gt=0)
    robot_id: int = Field(gt=0)
    group_code: str = Field(pattern="^[A-D]$")


class TournamentInitializeInput(BaseModel):
    category_id: int = Field(gt=0)
    teams: list[TournamentTeamAssignment] = Field(min_length=4, max_length=64)


class YukoInput(BaseModel):
    team_id: int = Field(gt=0)
    points_delta: int = Field(default=1, ge=-1, le=1)

    @field_validator("points_delta")
    @classmethod
    def non_zero_yuko_change(cls, value):
        if value == 0:
            raise ValueError("El ajuste de Yuko debe ser +1 o -1.")
        return value


def _round_robin_pairs(team_ids: list[int]) -> list[tuple[int, int]]:
    slots: list[int | None] = list(team_ids)
    if len(slots) % 2:
        slots.append(None)
    pairs: list[tuple[int, int]] = []
    for _ in range(len(slots) - 1):
        for index in range(len(slots) // 2):
            left, right = slots[index], slots[-1 - index]
            if left is not None and right is not None:
                pairs.append((left, right))
        slots = [slots[0], slots[-1], *slots[1:-1]]
    return pairs


def _tournament_matches(db: Session, event_id: int, category_id: int) -> list[dict]:
    rows = db.execute(text("""
      SELECT m.MatchId AS match_id,m.MatchNumber AS match_number,m.MatchStatus AS status,
        m.StageCode AS stage_code,m.GroupCode AS group_code,m.DohyoNumber AS dohyo_number,
        m.ScoreToWin AS score_to_win,m.BracketSlot AS bracket_slot,
        m.WinnerTeamId AS winner_team_id,m.LoserTeamId AS loser_team_id,
        cr.RoundNumber AS schedule_round,cr.Name AS round_name,
        ta.TeamId AS team_id_a,ta.Name AS team_a,ia.Name AS institution_a,
        mtA.RobotId AS robot_id_a,ra.Name AS robot_a,
        COALESCE(sa.Points,0) AS score_a,
        tb.TeamId AS team_id_b,tb.Name AS team_b,ib.Name AS institution_b,
        mtB.RobotId AS robot_id_b,rb.Name AS robot_b,
        COALESCE(sb.Points,0) AS score_b
      FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      JOIN dbo.CompetitionMatchTeams mtA ON mtA.MatchId=m.MatchId AND mtA.TeamPosition=1
      JOIN dbo.CompetitionMatchTeams mtB ON mtB.MatchId=m.MatchId AND mtB.TeamPosition=2
      JOIN dbo.Teams ta ON ta.TeamId=mtA.TeamId JOIN dbo.Institutions ia ON ia.InstitutionId=ta.InstitutionId
      JOIN dbo.Teams tb ON tb.TeamId=mtB.TeamId JOIN dbo.Institutions ib ON ib.InstitutionId=tb.InstitutionId
      LEFT JOIN dbo.Robots ra ON ra.RobotId=mtA.RobotId
      LEFT JOIN dbo.Robots rb ON rb.RobotId=mtB.RobotId
      OUTER APPLY (SELECT SUM(CONVERT(BIGINT,PointsDelta)) AS Points FROM dbo.ScoreEntries
        WHERE MatchId=m.MatchId AND TeamId=mtA.TeamId) sa
      OUTER APPLY (SELECT SUM(CONVERT(BIGINT,PointsDelta)) AS Points FROM dbo.ScoreEntries
        WHERE MatchId=m.MatchId AND TeamId=mtB.TeamId) sb
      WHERE cr.EventId=:event AND cr.CategoryId=:category AND m.StageCode<>'MANUAL'
      ORDER BY CASE m.StageCode WHEN 'GROUP' THEN 1 WHEN 'QUARTERFINAL' THEN 2
        WHEN 'SEMIFINAL' THEN 3 WHEN 'THIRD_PLACE' THEN 4 ELSE 5 END,
        m.GroupCode,m.MatchNumber
    """), {"event": event_id, "category": category_id}).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        for field in ("team_a", "team_b", "robot_a", "robot_b"):
            if item[field] is not None:
                item[field] = decrypt_text(item[field])
        item["score_a"] = int(item["score_a"] or 0)
        item["score_b"] = int(item["score_b"] or 0)
        item["score_to_win"] = int(item["score_to_win"])
        result.append(item)
    return result


def _tournament_snapshot(db: Session, event_id: int, category_id: int) -> dict:
    state = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one_or_none()
    assignments = db.execute(text("""
      SELECT g.GroupCode AS group_code,t.TeamId AS team_id,t.Name AS team,
        i.Name AS institution,r.RobotId AS robot_id,r.Name AS robot
      FROM dbo.TournamentTeamGroups g
      JOIN dbo.Teams t ON t.TeamId=g.TeamId JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      JOIN dbo.Robots r ON r.RobotId=g.RobotId
      WHERE g.EventId=:event AND g.CategoryId=:category
      ORDER BY g.GroupCode,t.Name,t.TeamId
    """), {"event": event_id, "category": category_id}).mappings().all()
    teams_by_group: dict[str, list[dict]] = {code: [] for code in "ABCD"}
    team_rows = {}
    for row in assignments:
        team = dict(row)
        team["team"] = decrypt_text(team["team"])
        team["robot"] = decrypt_text(team["robot"])
        team.update({"played": 0, "wins": 0, "losses": 0, "yukos_for": 0, "yukos_against": 0})
        teams_by_group[team["group_code"]].append(team)
        team_rows[team["team_id"]] = team

    matches = _tournament_matches(db, event_id, category_id)
    for match in matches:
        if match["stage_code"] != "GROUP" or match["status"] != "FINISHED":
            continue
        left, right = team_rows.get(match["team_id_a"]), team_rows.get(match["team_id_b"])
        if not left or not right:
            continue
        left["played"] += 1; right["played"] += 1
        left["yukos_for"] += match["score_a"]; left["yukos_against"] += match["score_b"]
        right["yukos_for"] += match["score_b"]; right["yukos_against"] += match["score_a"]
        if match["winner_team_id"] == left["team_id"]:
            left["wins"] += 1; right["losses"] += 1
        elif match["winner_team_id"] == right["team_id"]:
            right["wins"] += 1; left["losses"] += 1

    for code, group_teams in teams_by_group.items():
        def compare(left: dict, right: dict) -> int:
            if left["wins"] != right["wins"]:
                return -1 if left["wins"] > right["wins"] else 1
            left_diff = left["yukos_for"] - left["yukos_against"]
            right_diff = right["yukos_for"] - right["yukos_against"]
            if left_diff != right_diff:
                return -1 if left_diff > right_diff else 1
            direct = next((m for m in matches if m["stage_code"] == "GROUP"
                           and m["status"] == "FINISHED"
                           and {m["team_id_a"], m["team_id_b"]} == {left["team_id"], right["team_id"]}), None)
            if direct and direct["winner_team_id"] in (left["team_id"], right["team_id"]):
                return -1 if direct["winner_team_id"] == left["team_id"] else 1
            if left["yukos_for"] != right["yukos_for"]:
                return -1 if left["yukos_for"] > right["yukos_for"] else 1
            return (left["team"].casefold() > right["team"].casefold()) - (left["team"].casefold() < right["team"].casefold())

        from functools import cmp_to_key
        group_teams.sort(key=cmp_to_key(compare))
        for rank, team in enumerate(group_teams, 1):
            team["rank"] = rank
            team["difference"] = team["yukos_for"] - team["yukos_against"]

    live_rows = db.execute(text("""
      SELECT DohyoNumber AS dohyo_number,MatchId AS match_id
      FROM dbo.LiveDohyoMatches WHERE EventId=:event AND CategoryId=:category
      ORDER BY DohyoNumber
    """), {"event": event_id, "category": category_id}).mappings().all()
    by_id = {match["match_id"]: match for match in matches}
    boards = [{"dohyo_number": number, "match": None} for number in range(1, 5)]
    for row in live_rows:
        boards[int(row["dohyo_number"]) - 1]["match"] = by_id.get(row["match_id"])
    return {"event_id": event_id, "category_id": category_id, "phase": state or "NOT_CONFIGURED",
            "groups": teams_by_group, "matches": matches, "boards": boards}


def _ensure_tournament_round(db: Session, event_id: int, category_id: int,
                             name: str, actor_id: int) -> int:
    number = int(db.execute(text("""
      SELECT COALESCE(MAX(RoundNumber),0)+1 FROM dbo.CompetitionRounds WITH (UPDLOCK,HOLDLOCK)
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one())
    return int(db.execute(text("""
      INSERT dbo.CompetitionRounds(EventId,CategoryId,RoundNumber,Name,RoundStatus)
      OUTPUT INSERTED.RoundId VALUES(:event,:category,:number,:name,'SCHEDULED')
    """), {"event": event_id, "category": category_id, "number": number, "name": name}).scalar_one())


def _create_tournament_match(db: Session, event_id: int, category_id: int, round_id: int,
                             match_number: int, stage: str, dohyo: int,
                             teams: list[tuple[int, int]], actor_id: int,
                             group_code: str | None = None, slot: str | None = None,
                             score_to_win: int = 2) -> int:
    match_id = int(db.execute(text("""
      INSERT dbo.CompetitionMatches(RoundId,MatchNumber,MatchStatus,StageCode,GroupCode,
        DohyoNumber,ScoreToWin,BracketSlot)
      OUTPUT INSERTED.MatchId
      VALUES(:round,:number,'SCHEDULED',:stage,:group,:dohyo,:target,:slot)
    """), {"round": round_id, "number": match_number, "stage": stage,
          "group": group_code, "dohyo": dohyo, "target": score_to_win, "slot": slot}).scalar_one())
    for position, (team_id, robot_id) in enumerate(teams, 1):
        db.execute(text("""
          INSERT dbo.CompetitionMatchTeams(MatchId,TeamId,RobotId,TeamPosition)
          VALUES(:match,:team,:robot,:position)
        """), {"match": match_id, "team": team_id, "robot": robot_id, "position": position})
    return match_id


def _set_primary_live_match(db: Session, match_id: int, actor_id: int) -> None:
    current = db.execute(text("""
      SELECT MatchId FROM dbo.ActiveCombat WITH (UPDLOCK,HOLDLOCK) WHERE ActiveCombatId=1
    """)).scalar_one_or_none()
    if current == match_id:
        return
    if current is None:
        db.execute(text("INSERT dbo.ActiveCombat(ActiveCombatId,MatchId,UpdatedByUserId) VALUES(1,:match,:actor)"),
                   {"match": match_id, "actor": actor_id})
    else:
        db.execute(text("""
          UPDATE dbo.ActiveCombat SET MatchId=:match,UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE ActiveCombatId=1
        """), {"match": match_id, "actor": actor_id})
        db.execute(text("""
          INSERT dbo.ActiveCombatHistory(PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
          VALUES(:old,:match,:actor,'REPLACED','AVANCE DE FASE DEL TORNEO')
        """), {"old": current, "match": match_id, "actor": actor_id})


def _set_live_dohyo(db: Session, event_id: int, category_id: int, dohyo: int,
                    match_id: int | None, actor_id: int) -> None:
    existing = db.execute(text("""
      SELECT MatchId FROM dbo.LiveDohyoMatches WITH (UPDLOCK,HOLDLOCK)
      WHERE EventId=:event AND CategoryId=:category AND DohyoNumber=:dohyo
    """), {"event": event_id, "category": category_id, "dohyo": dohyo}).scalar_one_or_none()
    if match_id is None:
        if existing is not None:
            db.execute(text("""DELETE dbo.LiveDohyoMatches
              WHERE EventId=:event AND CategoryId=:category AND DohyoNumber=:dohyo"""),
                       {"event": event_id, "category": category_id, "dohyo": dohyo})
        return
    if existing is None:
        db.execute(text("""
          INSERT dbo.LiveDohyoMatches(EventId,CategoryId,DohyoNumber,MatchId,UpdatedByUserId)
          VALUES(:event,:category,:dohyo,:match,:actor)
        """), {"event": event_id, "category": category_id, "dohyo": dohyo,
              "match": match_id, "actor": actor_id})
    elif existing != match_id:
        db.execute(text("""
          UPDATE dbo.LiveDohyoMatches SET MatchId=:match,UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE EventId=:event AND CategoryId=:category AND DohyoNumber=:dohyo
        """), {"event": event_id, "category": category_id, "dohyo": dohyo,
              "match": match_id, "actor": actor_id})


def _create_match_batch(db: Session, event_id: int, category_id: int, stage: str,
                        fixtures: list[tuple[int, str, list[int], int]], actor_id: int) -> list[int]:
    round_id = _ensure_tournament_round(db, event_id, category_id, stage, actor_id)
    matches = []
    for number, (dohyo, slot, team_ids, score_to_win) in enumerate(fixtures, 1):
        robot_ids = db.execute(text("""
          SELECT TeamId,RobotId FROM dbo.TournamentTeamGroups
          WHERE EventId=:event AND CategoryId=:category AND TeamId IN (:left,:right)
        """), {"event": event_id, "category": category_id,
              "left": team_ids[0], "right": team_ids[1]}).all()
        robot_by_team = {int(team_id): int(robot_id) for team_id, robot_id in robot_ids}
        if any(team_id not in robot_by_team for team_id in team_ids):
            raise HTTPException(409, "Un equipo de la llave ya no está asignado a este torneo.")
        match_id = _create_tournament_match(db,event_id,category_id,round_id,number,stage,dohyo,
             [(team_ids[0],robot_by_team[team_ids[0]]),(team_ids[1],robot_by_team[team_ids[1]])],
             actor_id,slot=slot,score_to_win=score_to_win)
        db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:id"),
                   {"id": match_id})
        _set_live_dohyo(db,event_id,category_id,dohyo,match_id,actor_id)
        matches.append(match_id)
    if matches:
        _set_primary_live_match(db,matches[0],actor_id)
    return matches


def _progress_tournament(db: Session, event_id: int, category_id: int, actor_id: int) -> None:
    phase = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one_or_none()
    if phase in (None, "FINISHED"):
        return
    unfinished = int(db.execute(text("""
      SELECT COUNT(*) FROM dbo.CompetitionMatches m JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode=:phase
        AND m.MatchStatus<>'FINISHED'
    """), {"event": event_id, "category": category_id, "phase": phase}).scalar_one())
    if unfinished:
        return
    for dohyo in range(1, 5):
        _set_live_dohyo(db,event_id,category_id,dohyo,None,actor_id)
    fixtures: list[tuple[int, str, list[int], int]] = []
    next_phase: str
    if phase == "GROUP":
        snapshot = _tournament_snapshot(db,event_id,category_id)
        groups = snapshot["groups"]
        if any(len(groups[code]) < 2 for code in "ABCD"):
            raise HTTPException(409, "Los cuatro grupos necesitan al menos dos equipos para formar los cuartos.")
        formulas = [(1,"QF1",groups["A"][0]["team_id"],groups["B"][1]["team_id"],2),
                    (2,"QF2",groups["C"][0]["team_id"],groups["D"][1]["team_id"],2),
                    (3,"QF3",groups["B"][0]["team_id"],groups["A"][1]["team_id"],2),
                    (4,"QF4",groups["D"][0]["team_id"],groups["C"][1]["team_id"],2)]
        fixtures = [(dohyo,slot,[left,right],target) for dohyo,slot,left,right,target in formulas]
        next_phase = "QUARTERFINAL"
    elif phase == "QUARTERFINAL":
        results = {row["bracket_slot"]: row for row in _tournament_matches(db,event_id,category_id)
                   if row["stage_code"] == "QUARTERFINAL"}
        fixtures = [(1,"SF1",[results["QF1"]["winner_team_id"],results["QF2"]["winner_team_id"]],2),
                    (2,"SF2",[results["QF3"]["winner_team_id"],results["QF4"]["winner_team_id"]],2)]
        next_phase = "SEMIFINAL"
    elif phase == "SEMIFINAL":
        results = {row["bracket_slot"]: row for row in _tournament_matches(db,event_id,category_id)
                   if row["stage_code"] == "SEMIFINAL"}
        fixtures = [(1,"THIRD",[results["SF1"]["loser_team_id"],results["SF2"]["loser_team_id"]],2)]
        next_phase = "THIRD_PLACE"
    elif phase == "THIRD_PLACE":
        results = {row["bracket_slot"]: row for row in _tournament_matches(db,event_id,category_id)
                   if row["stage_code"] == "SEMIFINAL"}
        fixtures = [(1,"FINAL",[results["SF1"]["winner_team_id"],results["SF2"]["winner_team_id"]],3)]
        next_phase = "FINAL"
    elif phase == "FINAL":
        db.execute(text("""
          UPDATE dbo.TournamentPhaseState SET CurrentPhase='FINISHED',UpdatedByUserId=:actor,
            UpdatedAt=SYSUTCDATETIME() WHERE EventId=:event AND CategoryId=:category
        """), {"actor": actor_id, "event": event_id, "category": category_id})
        return
    else:
        return
    _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id)
    db.execute(text("""
      UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,UpdatedByUserId=:actor,
        UpdatedAt=SYSUTCDATETIME() WHERE EventId=:event AND CategoryId=:category
    """), {"phase": next_phase, "actor": actor_id, "event": event_id, "category": category_id})


@router.get("/events/{event_id}/tournament")
def get_tournament(event_id: int, category_id: int = Query(gt=0),
                   user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:event"), {"event": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    return _tournament_snapshot(db,event_id,category_id)


@router.post("/events/{event_id}/tournament")
def initialize_tournament(event_id: int, payload: TournamentInitializeInput,
                          user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:event"), {"event": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    if not db.execute(text("""
      SELECT 1 FROM dbo.EventCategories WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": payload.category_id}).first():
        raise HTTPException(422, "La categoría no pertenece a este evento.")
    group_codes = {code for code in "ABCD"}
    supplied_groups = {team.group_code for team in payload.teams}
    if supplied_groups != group_codes:
        raise HTTPException(422, "Asigne al menos un equipo a cada grupo (A, B, C y D).")
    team_ids = [team.team_id for team in payload.teams]
    robot_ids = [team.robot_id for team in payload.teams]
    if len(set(team_ids)) != len(team_ids) or len(set(robot_ids)) != len(robot_ids):
        raise HTTPException(422, "No repita equipos ni robots en la asignación de grupos.")
    try:
        existing = db.execute(text("""
          SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
          WHERE EventId=:event AND CategoryId=:category
        """), {"event": event_id, "category": payload.category_id}).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "El torneo de esta categoría ya fue configurado. Use la acción de reinicio solo antes de iniciar la puntuación.")
        assigned: dict[str, list[int]] = {code: [] for code in group_codes}
        for team in payload.teams:
            approved = db.execute(text("""
              SELECT 1 FROM dbo.Registrations r
              JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
              WHERE r.EventId=:event AND r.CategoryId=:category AND r.TeamId=:team AND r.RobotId=:robot
            """), {"event": event_id, "category": payload.category_id,
                  "team": team.team_id, "robot": team.robot_id}).first()
            if not approved:
                raise HTTPException(422, "Cada equipo y robot debe tener inscripción aprobada en esta categoría.")
            assigned[team.group_code].append(team.team_id)
            db.execute(text("""
              INSERT dbo.TournamentTeamGroups(EventId,CategoryId,TeamId,RobotId,GroupCode,AssignedByUserId)
              VALUES(:event,:category,:team,:robot,:group,:actor)
            """), {"event": event_id, "category": payload.category_id,
                  "team": team.team_id, "robot": team.robot_id,
                  "group": team.group_code, "actor": user["user_id"]})

        expected_group_sizes = {"A": 5, "B": 5, "C": 5, "D": 6}
        actual_group_sizes = {code: len(team_ids) for code, team_ids in assigned.items()}
        if actual_group_sizes != expected_group_sizes:
            raise HTTPException(422, "Para el torneo del jueves se requieren 5 equipos en A, B y C, y 6 en D.")

        queues = {code: _round_robin_pairs(assigned[code]) for code in "ABCD"}
        frame_count = max(len(queue) for queue in queues.values())
        for frame in range(frame_count):
            round_id = _ensure_tournament_round(db,event_id,payload.category_id,
                                                 f"Grupos · Jornada {frame+1}",user["user_id"])
            for dohyo, code in enumerate("ABCD", 1):
                if frame >= len(queues[code]):
                    continue
                left, right = queues[code][frame]
                robots = {item.team_id: item.robot_id for item in payload.teams}
                _create_tournament_match(db,event_id,payload.category_id,round_id,dohyo,
                    "GROUP",dohyo,[(left,robots[left]),(right,robots[right])],user["user_id"],
                    group_code=code,score_to_win=2)
        db.execute(text("""
          INSERT dbo.TournamentPhaseState(EventId,CategoryId,CurrentPhase,CreatedByUserId,UpdatedByUserId)
          VALUES(:event,:category,'GROUP',:actor,:actor)
        """), {"event": event_id, "category": payload.category_id, "actor": user["user_id"]})
        db.commit()
        return _tournament_snapshot(db,event_id,payload.category_id)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo crear el calendario: revise equipos, categoría y rondas existentes.")
    except Exception:
        db.rollback()
        raise


@router.post("/events/{event_id}/tournament/start")
async def start_tournament(event_id: int, category_id: int = Query(gt=0),
                           user=Depends(require_roles(*STAFF))):
    def apply():
        db = SessionLocal()
        try:
            state = db.execute(text("""
              SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
              WHERE EventId=:event AND CategoryId=:category
            """), {"event": event_id, "category": category_id}).scalar_one_or_none()
            if state is None:
                raise HTTPException(404, "Primero configure los grupos y el calendario.")
            if state != "GROUP":
                raise HTTPException(409, "El torneo ya avanzó de la fase de grupos.")
            current = db.execute(text("""
              SELECT ac.MatchId,m.MatchStatus,m.StageCode FROM dbo.ActiveCombat ac
              JOIN dbo.CompetitionMatches m ON m.MatchId=ac.MatchId
              WHERE ac.ActiveCombatId=1
            """)).first()
            if current and current.StageCode == "MANUAL" and current.MatchStatus == "LIVE":
                raise HTTPException(409, "Finalice el combate manual activo antes de iniciar las cuatro pistas del torneo.")
            first_ids=[]
            for dohyo, code in enumerate("ABCD",1):
                match_id=db.execute(text("""
                  SELECT TOP (1) m.MatchId FROM dbo.CompetitionMatches m
                  JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
                  WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode='GROUP'
                    AND m.GroupCode=:group AND m.MatchStatus='SCHEDULED'
                  ORDER BY r.RoundNumber,m.MatchNumber
                """), {"event":event_id,"category":category_id,"group":code}).scalar_one_or_none()
                if match_id is not None:
                    db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:id"),{"id":match_id})
                    _set_live_dohyo(db,event_id,category_id,dohyo,int(match_id),user["user_id"])
                    first_ids.append(int(match_id))
            if not first_ids:
                raise HTTPException(409, "No hay encuentros de grupo pendientes.")
            _write_event_status(db,event_id,"LIVE",user["user_id"],"Inicio de fase de grupos")
            _set_primary_live_match(db,first_ids[0],user["user_id"])
            snapshot=_current_combat_snapshot(db)
            db.commit()
            return snapshot
        except HTTPException:
            db.rollback(); raise
        finally:
            db.close()
    snapshot=await asyncio.to_thread(apply)
    await live_combat_connections.broadcast(snapshot)
    return snapshot


@router.post("/events/{event_id}/tournament/matches/{match_id}/yukos")
async def award_yuko(event_id: int, match_id: int, payload: YukoInput,
                     category_id: int = Query(gt=0), user=Depends(require_roles(*STAFF))):
    def apply():
        db=SessionLocal()
        try:
            match=db.execute(text("""
              SELECT m.MatchId,m.RoundId,m.MatchStatus,m.StageCode,m.ScoreToWin,m.GroupCode,
                m.WinnerTeamId,
                cr.EventId,e.CompetitionStatus
              FROM dbo.CompetitionMatches m WITH (UPDLOCK,HOLDLOCK)
              JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
              JOIN dbo.Events e ON e.EventId=cr.EventId
              WHERE m.MatchId=:match AND cr.EventId=:event AND cr.CategoryId=:category
            """), {"match":match_id,"event":event_id,"category":category_id}).mappings().first()
            if match is None: raise HTTPException(404,"Encuentro no encontrado.")
            editable_finished_group = (match["MatchStatus"] == "FINISHED"
                                       and match["StageCode"] == "GROUP"
                                       and payload.points_delta < 0)
            if (match["MatchStatus"] != "LIVE" and not editable_finished_group) or match["CompetitionStatus"]!="LIVE":
                raise HTTPException(409,"El encuentro debe estar en vivo para registrar un Yuko; solo se permite corregir Yukos en un grupo finalizado.")
            if not db.execute(text("""
              SELECT 1 FROM dbo.LiveDohyoMatches WHERE EventId=:event AND CategoryId=:category AND MatchId=:match
            """), {"event":event_id,"category":category_id,"match":match_id}).first():
                raise HTTPException(409,"El encuentro no está asignado a un dohyo en vivo.")
            teams=db.execute(text("""SELECT TeamId FROM dbo.CompetitionMatchTeams
              WHERE MatchId=:match ORDER BY TeamPosition"""),{"match":match_id}).scalars().all()
            if payload.team_id not in teams: raise HTTPException(422,"El equipo no participa en este encuentro.")
            totals={int(row.TeamId):int(row.Points or 0) for row in db.execute(text("""
              SELECT TeamId,SUM(CONVERT(BIGINT,PointsDelta)) AS Points FROM dbo.ScoreEntries
              WHERE MatchId=:match GROUP BY TeamId
            """),{"match":match_id}).all()}
            totals={team:int(totals.get(team,0)) for team in teams}
            if totals[payload.team_id] + payload.points_delta < 0:
                raise HTTPException(409,"El marcador no puede quedar por debajo de cero Yukos.")
            if payload.points_delta > 0 and totals[payload.team_id]>=int(match["ScoreToWin"]):
                raise HTTPException(409,"Ese equipo ya alcanzó los Yukos necesarios para ganar.")
            db.execute(text("""
              INSERT dbo.ScoreEntries(EventId,CategoryId,TeamId,RoundId,MatchId,PointsDelta,
                Reason,IdempotencyKey,CreatedByUserId)
              VALUES(:event,:category,:team,:round,:match,:delta,:reason,:key,:actor)
            """), {"event":event_id,"category":category_id,"team":payload.team_id,
                  "round":match["RoundId"],"match":match_id,"delta":payload.points_delta,
                  "reason":"Yuko otorgado por el administrador" if payload.points_delta > 0 else "Corrección administrativa de Yuko",
                  "key":uuid4(),"actor":user["user_id"]})
            totals[payload.team_id]+=payload.points_delta
            if payload.points_delta < 0 and match["MatchStatus"] == "FINISHED":
                winner_points = totals.get(int(match["WinnerTeamId"] or 0), 0)
                if winner_points < int(match["ScoreToWin"]):
                    db.execute(text("""
                      UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE',WinnerTeamId=NULL,LoserTeamId=NULL
                      WHERE MatchId=:match
                    """), {"match":match_id})
                    if match["StageCode"] != "GROUP":
                        db.execute(text("""
                          UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,UpdatedByUserId=:actor,
                            UpdatedAt=SYSUTCDATETIME() WHERE EventId=:event AND CategoryId=:category
                        """), {"phase":match["StageCode"],"actor":user["user_id"],"event":event_id,"category":category_id})
            if payload.points_delta > 0 and totals[payload.team_id]>=int(match["ScoreToWin"]):
                loser=next(team for team in teams if team!=payload.team_id)
                db.execute(text("""
                  UPDATE dbo.CompetitionMatches SET MatchStatus='FINISHED',WinnerTeamId=:winner,
                    LoserTeamId=:loser WHERE MatchId=:match
                """), {"winner":payload.team_id,"loser":loser,"match":match_id})
                if match["StageCode"]!="GROUP":
                    _progress_tournament(db,event_id,category_id,user["user_id"])
            db.execute(text("""
              UPDATE dbo.ActiveCombat SET UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
              WHERE ActiveCombatId=1 AND MatchId=:match
            """), {"actor":user["user_id"],"match":match_id})
            snapshot=_current_combat_snapshot(db)
            db.commit()
            return snapshot
        except HTTPException:
            db.rollback(); raise
        except IntegrityError:
            db.rollback(); raise HTTPException(409,"No se pudo registrar el Yuko por un conflicto de datos.")
        finally: db.close()
    snapshot=await asyncio.to_thread(apply)
    await live_combat_connections.broadcast(snapshot)
    return snapshot


@router.post("/events/{event_id}/tournament/dohyos/{dohyo_number}/advance")
async def advance_dohyo(event_id: int, dohyo_number: int, category_id: int = Query(gt=0),
                        user=Depends(require_roles(*STAFF))):
    if dohyo_number not in range(1,5): raise HTTPException(422,"El dohyo debe ser del 1 al 4.")
    def apply():
        db=SessionLocal()
        try:
            current=db.execute(text("""
              SELECT m.MatchId,m.MatchStatus,m.StageCode,m.GroupCode FROM dbo.LiveDohyoMatches l
              JOIN dbo.CompetitionMatches m ON m.MatchId=l.MatchId
              WHERE l.EventId=:event AND l.CategoryId=:category AND l.DohyoNumber=:dohyo
            """), {"event":event_id,"category":category_id,"dohyo":dohyo_number}).mappings().first()
            if current is None: raise HTTPException(404,"Este dohyo no tiene un encuentro seleccionado.")
            if current["MatchStatus"]!="FINISHED": raise HTTPException(409,"El encuentro debe terminar antes de avanzar.")
            if current["StageCode"]!="GROUP": raise HTTPException(409,"Las fases eliminatorias avanzan automáticamente al terminar todos sus combates.")
            next_match=db.execute(text("""
              SELECT TOP (1) m.MatchId FROM dbo.CompetitionMatches m
              JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
              WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode='GROUP'
                AND m.GroupCode=:group AND m.MatchStatus='SCHEDULED'
              ORDER BY r.RoundNumber,m.MatchNumber
            """), {"event":event_id,"category":category_id,"group":current["GroupCode"]}).scalar_one_or_none()
            if next_match is None:
                _set_live_dohyo(db,event_id,category_id,dohyo_number,None,user["user_id"])
                _progress_tournament(db,event_id,category_id,user["user_id"])
            else:
                db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:id"),{"id":next_match})
                _set_live_dohyo(db,event_id,category_id,dohyo_number,int(next_match),user["user_id"])
            primary=db.execute(text("""
              SELECT TOP (1) MatchId FROM dbo.LiveDohyoMatches
              WHERE EventId=:event AND CategoryId=:category ORDER BY DohyoNumber
            """), {"event":event_id,"category":category_id}).scalar_one_or_none()
            if primary is not None: _set_primary_live_match(db,int(primary),user["user_id"])
            snapshot=_current_combat_snapshot(db)
            db.commit()
            return snapshot
        except HTTPException:
            db.rollback(); raise
        finally: db.close()
    snapshot=await asyncio.to_thread(apply)
    await live_combat_connections.broadcast(snapshot)
    return snapshot


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
    is_live_dohyo = False
    if match_id is not None:
        is_live_dohyo = bool(db.execute(text("""
          SELECT 1 FROM dbo.LiveDohyoMatches WHERE MatchId=:match
        """), {"match": match_id}).first())
    if current and ((match_id is not None and (current.MatchId == match_id or is_live_dohyo))
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
    db.execute(text("""UPDATE dbo.Events SET CompetitionStatus=:status,
        IsActive=CASE WHEN :status IN ('FINISHED','CANCELLED') THEN 0
                      WHEN :status IN ('SCHEDULED','LIVE','PAUSED') THEN 1 ELSE IsActive END
        WHERE EventId=:id"""),
               {"status": payload.status, "id": event_id})
    if previous != payload.status:
        db.execute(text("""
          INSERT dbo.CompetitionEventStatusHistory(EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
          VALUES(:event,:previous,:next,:actor,:reason)
        """), {"event": event_id, "previous": previous, "next": payload.status,
              "actor": user["user_id"], "reason": payload.reason.strip() if payload.reason else None})
        db.execute(text("""INSERT dbo.EventStatusHistory(EventId,PreviousStatus,NewStatus,Reason,ActorUserId)
          VALUES(:event,:previous,:next,:reason,:actor)"""),
          {"event":event_id,"previous":previous,"next":payload.status,
           "reason":payload.reason.strip() if payload.reason else None,"actor":user["user_id"]})
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
                  limit: int = Query(5, ge=1, le=100),
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
                limit: int = Query(5, ge=1, le=100), user=Depends(require_roles(*STAFF)),
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
                               limit: int = Query(5, ge=1, le=100), db: Session = Depends(get_db)):
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
                page: int = Query(1, ge=1), limit: int = Query(5, ge=1, le=100),
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
                 page: int = Query(1, ge=1), limit: int = Query(5, ge=1, le=100),
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
        m.PublicDetails AS details,m.TimerEnabled AS timer_enabled,
        m.TimerDurationSeconds AS timer_duration_seconds,m.TimerStatus AS timer_status,
        m.TimerDirection AS timer_direction,
        m.TimerStartedAt AS timer_started_at,m.TimerUpdatedAt AS timer_updated_at,
        CASE
          WHEN m.TimerStatus='RUNNING' AND m.TimerDirection='DOWN' THEN
            CASE WHEN m.TimerRemainingSeconds-DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())<0
                 THEN 0 ELSE m.TimerRemainingSeconds-DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME()) END
          WHEN m.TimerStatus='RUNNING' AND m.TimerDirection='UP' THEN
            CASE WHEN m.TimerElapsedSeconds+DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())>m.TimerDurationSeconds
                 THEN m.TimerDurationSeconds ELSE m.TimerElapsedSeconds+DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME()) END
          WHEN m.TimerDirection='UP' THEN m.TimerElapsedSeconds
          ELSE m.TimerRemainingSeconds
        END AS timer_current_seconds,
        CASE WHEN m.TimerStatus='RUNNING' AND (
               (m.TimerDirection='DOWN' AND m.TimerRemainingSeconds-DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())<=0)
               OR (m.TimerDirection='UP' AND m.TimerElapsedSeconds+DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())>=m.TimerDurationSeconds))
             THEN 'FINISHED' ELSE m.TimerStatus END AS timer_display_status,
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
                "ultimaActualizacion": "--:--",
                "cronometro": {"enabled": False, "direction": "DOWN", "duration_seconds": 180,
                               "current_seconds": 180, "remaining_seconds": 180,
                               "elapsed_seconds": 0, "status": "STOPPED",
                               "started_at": None, "updated_at": None},
                "tiempoSegundos": 180, "cronometroActivo": False}
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
    timer_current = max(0, min(int(first["timer_duration_seconds"]), int(first["timer_current_seconds"])))
    timer_direction = first["timer_direction"]
    timer = {
        "enabled": bool(first["timer_enabled"]),
        "duration_seconds": int(first["timer_duration_seconds"]),
        "direction": timer_direction,
        "current_seconds": timer_current,
        "remaining_seconds": timer_current if timer_direction == "DOWN" else int(first["timer_duration_seconds"]) - timer_current,
        "elapsed_seconds": int(first["timer_duration_seconds"]) - timer_current if timer_direction == "DOWN" else timer_current,
        "status": first["timer_display_status"],
        "started_at": first["timer_started_at"].isoformat() if first["timer_started_at"] else None,
        "updated_at": first["timer_updated_at"].isoformat() if first["timer_updated_at"] else None,
    }
    robot_a = {"nombre": decrypt_text(first["robot_name"]),
               "institucion": first["institution_name"], "puntos": first_points}
    robot_b = {"nombre": decrypt_text(second["robot_name"]),
               "institucion": second["institution_name"], "puntos": second_points}
    snapshot = {
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
        "cronometro": timer,
        "tiempoSegundos": timer["current_seconds"],
        "cronometroActivo": timer["enabled"] and timer["status"] == "RUNNING",
        "updated_at": updated_at.isoformat() if updated_at else None,
        "ultimaActualizacion": updated_at.strftime("%H:%M") if updated_at else "--:--",
    }
    tournament = _tournament_snapshot(db, int(first["event_id"]), int(first["category_id"]))
    if tournament["phase"] != "NOT_CONFIGURED":
        snapshot.update({"tournament": tournament, "boards": tournament["boards"],
                         "fase": tournament["phase"], "combates": tournament["matches"]})
    return snapshot


def _load_current_combat_snapshot() -> dict:
    db = SessionLocal()
    try:
        return _current_combat_snapshot(db)
    finally:
        db.close()


def _apply_match_timer_change(action: str, user: dict, config: MatchTimerConfig | None = None) -> dict:
    db = SessionLocal()
    try:
        match = db.execute(text("""
          SELECT m.MatchId,m.MatchStatus AS MatchStatus,e.CompetitionStatus AS EventStatus,
            m.TimerEnabled,m.TimerDurationSeconds,m.TimerRemainingSeconds,
            m.TimerElapsedSeconds,m.TimerDirection,m.TimerStatus,m.TimerStartedAt,
            CASE
              WHEN m.TimerStatus='RUNNING' AND m.TimerDirection='DOWN' THEN
                CASE WHEN m.TimerRemainingSeconds-DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())<0
                     THEN 0 ELSE m.TimerRemainingSeconds-DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME()) END
              WHEN m.TimerStatus='RUNNING' AND m.TimerDirection='UP' THEN
                CASE WHEN m.TimerElapsedSeconds+DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME())>m.TimerDurationSeconds
                     THEN m.TimerDurationSeconds ELSE m.TimerElapsedSeconds+DATEDIFF_BIG(SECOND,m.TimerStartedAt,SYSUTCDATETIME()) END
              WHEN m.TimerDirection='UP' THEN m.TimerElapsedSeconds
              ELSE m.TimerRemainingSeconds
            END AS CurrentNow
          FROM dbo.ActiveCombat ac WITH (UPDLOCK,HOLDLOCK)
          JOIN dbo.CompetitionMatches m WITH (UPDLOCK,HOLDLOCK) ON m.MatchId=ac.MatchId
          JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
          JOIN dbo.Events e ON e.EventId=cr.EventId
          WHERE ac.ActiveCombatId=1
        """)).mappings().first()
        if match is None:
            raise HTTPException(404, "No hay un combate activo para controlar el cronómetro.")

        if action == "configure":
            assert config is not None
            db.execute(text("""
              UPDATE dbo.CompetitionMatches SET TimerEnabled=:enabled,
                TimerDurationSeconds=:duration,TimerRemainingSeconds=:duration,
                TimerElapsedSeconds=0,TimerDirection=:direction,
                TimerStatus=CASE WHEN :enabled=1 AND :match_status='LIVE' AND :event_status='LIVE'
                                  THEN 'RUNNING'
                                 WHEN :enabled=1 AND :match_status='LIVE' AND :event_status='PAUSED'
                                  THEN 'PAUSED' ELSE 'STOPPED' END,
                TimerStartedAt=CASE WHEN :enabled=1 AND :match_status='LIVE' AND :event_status='LIVE'
                                    THEN SYSUTCDATETIME() ELSE NULL END,
                TimerUpdatedAt=SYSUTCDATETIME()
              WHERE MatchId=:match
            """), {"enabled": config.enabled, "duration": config.duration_seconds,
                  "direction": config.direction,
                  "match_status": match["MatchStatus"], "event_status": match["EventStatus"],
                  "match": match["MatchId"]})
        elif action == "start":
            if not match["TimerEnabled"]:
                raise HTTPException(409, "Activa el cronómetro antes de iniciarlo.")
            current = int(match["CurrentNow"])
            exhausted = (current <= 0 if match["TimerDirection"] == "DOWN"
                         else current >= int(match["TimerDurationSeconds"]))
            if exhausted:
                db.execute(text("""
                  UPDATE dbo.CompetitionMatches SET TimerStatus='FINISHED',TimerStartedAt=NULL,
                    TimerUpdatedAt=SYSUTCDATETIME() WHERE MatchId=:match
                """), {"match": match["MatchId"]})
            elif match["TimerStatus"] != "RUNNING":
                if match["TimerDirection"] == "DOWN":
                    db.execute(text("UPDATE dbo.CompetitionMatches SET TimerRemainingSeconds=:current WHERE MatchId=:match"),
                               {"current": current, "match": match["MatchId"]})
                else:
                    db.execute(text("UPDATE dbo.CompetitionMatches SET TimerElapsedSeconds=:current WHERE MatchId=:match"),
                               {"current": current, "match": match["MatchId"]})
                db.execute(text("""
                  UPDATE dbo.CompetitionMatches SET TimerStatus='RUNNING',
                    TimerStartedAt=SYSUTCDATETIME(),TimerUpdatedAt=SYSUTCDATETIME()
                  WHERE MatchId=:match
                """), {"match": match["MatchId"]})
        elif action == "pause":
            if match["TimerStatus"] == "RUNNING":
                current = int(match["CurrentNow"])
                finished = (current <= 0 if match["TimerDirection"] == "DOWN"
                            else current >= int(match["TimerDurationSeconds"]))
                if match["TimerDirection"] == "DOWN":
                    db.execute(text("""
                      UPDATE dbo.CompetitionMatches SET TimerRemainingSeconds=:current,
                        TimerStatus=:status,TimerStartedAt=NULL,TimerUpdatedAt=SYSUTCDATETIME()
                      WHERE MatchId=:match
                    """), {"current": current, "status": "FINISHED" if finished else "PAUSED",
                          "match": match["MatchId"]})
                else:
                    db.execute(text("""
                      UPDATE dbo.CompetitionMatches SET TimerElapsedSeconds=:current,
                        TimerStatus=:status,TimerStartedAt=NULL,TimerUpdatedAt=SYSUTCDATETIME()
                      WHERE MatchId=:match
                    """), {"current": current, "status": "FINISHED" if finished else "PAUSED",
                          "match": match["MatchId"]})
        elif action == "reset":
            db.execute(text("""
              UPDATE dbo.CompetitionMatches SET TimerRemainingSeconds=TimerDurationSeconds,
                TimerElapsedSeconds=0,TimerStatus='STOPPED',TimerStartedAt=NULL,
                TimerUpdatedAt=SYSUTCDATETIME() WHERE MatchId=:match
            """), {"match": match["MatchId"]})
        else:
            raise HTTPException(422, "Operación de cronómetro desconocida.")

        db.execute(text("""
          UPDATE dbo.ActiveCombat SET UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE ActiveCombatId=1 AND MatchId=:match
        """), {"actor": user["user_id"], "match": match["MatchId"]})
        db.execute(text("""
          INSERT dbo.ActiveCombatHistory(PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
          VALUES(:match,:match,:actor,'TIMER_CHANGED',:reason)
        """), {"match": match["MatchId"], "actor": user["user_id"], "reason": action.upper()})
        snapshot = _current_combat_snapshot(db)
        db.commit()
        return snapshot
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo actualizar el cronómetro por un conflicto de integridad.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _pause_match_timer(db: Session, match_id: int) -> None:
    db.execute(text("""
      UPDATE dbo.CompetitionMatches SET
        TimerRemainingSeconds=CASE WHEN TimerDirection='DOWN' THEN
          CASE WHEN TimerRemainingSeconds-DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME())<0
               THEN 0 ELSE TimerRemainingSeconds-DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME()) END
          ELSE TimerRemainingSeconds END,
        TimerElapsedSeconds=CASE WHEN TimerDirection='UP' THEN
          CASE WHEN TimerElapsedSeconds+DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME())>TimerDurationSeconds
               THEN TimerDurationSeconds ELSE TimerElapsedSeconds+DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME()) END
          ELSE TimerElapsedSeconds END,
        TimerStatus=CASE WHEN
          (TimerDirection='DOWN' AND TimerRemainingSeconds-DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME())<=0)
          OR (TimerDirection='UP' AND TimerElapsedSeconds+DATEDIFF_BIG(SECOND,TimerStartedAt,SYSUTCDATETIME())>=TimerDurationSeconds)
          THEN 'FINISHED' ELSE 'PAUSED' END,
        TimerStartedAt=NULL,TimerUpdatedAt=SYSUTCDATETIME()
      WHERE MatchId=:match AND TimerStatus='RUNNING'
    """), {"match": match_id})


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
            db.execute(text("""UPDATE dbo.Events SET CompetitionStatus=:status,
              IsActive=CASE WHEN :status IN ('FINISHED','CANCELLED') THEN 0
                            WHEN :status IN ('SCHEDULED','LIVE','PAUSED') THEN 1 ELSE IsActive END
              WHERE EventId=:event"""),
                       {"status": next_status, "event": event_id})
            db.execute(text("""
              INSERT dbo.CompetitionEventStatusHistory
                (EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
              VALUES(:event,:previous,:next,:actor,:reason)
            """), {"event": event_id, "previous": previous, "next": next_status,
                  "actor": actor_id, "reason": reason})
            db.execute(text("""INSERT dbo.EventStatusHistory(EventId,PreviousStatus,NewStatus,Reason,ActorUserId)
              VALUES(:event,:previous,:next,:reason,:actor)"""),
              {"event":event_id,"previous":previous,"next":next_status,"reason":reason,"actor":actor_id})
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
            if payload.status in {"PAUSADO", "FINALIZADO", "CANCELADO"}:
                # Stopping/finishing a match must not leave its official timer
                # counting in the background. Resuming a match requires an
                # explicit timer start from authorized staff.
                _pause_match_timer(db, match_id)
            db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus=:status WHERE MatchId=:id"),
                       {"status": effective_match_status, "id": match_id})
            if payload.status == "EN_VIVO":
                # Start or resume the configured clock in the same transaction
                # as the match transition; spectators receive both together.
                db.execute(text("""
                  UPDATE dbo.CompetitionMatches SET TimerStatus='RUNNING',
                    TimerStartedAt=SYSUTCDATETIME(),TimerUpdatedAt=SYSUTCDATETIME()
                  WHERE MatchId=:id AND TimerEnabled=1 AND TimerStatus IN ('STOPPED','PAUSED')
                    AND ((TimerDirection='DOWN' AND TimerRemainingSeconds>0)
                      OR (TimerDirection='UP' AND TimerElapsedSeconds<TimerDurationSeconds))
                """), {"id": match_id})
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
            if current_match_id is not None:
                old_timer = db.execute(text("""
                  SELECT TimerStatus FROM dbo.CompetitionMatches WITH (UPDLOCK,HOLDLOCK)
                  WHERE MatchId=:match
                """), {"match": current_match_id}).scalar_one_or_none()
                if old_timer == "RUNNING":
                    _pause_match_timer(db, current_match_id)
                    db.execute(text("""
                      INSERT dbo.ActiveCombatHistory(PreviousMatchId,NewMatchId,ActorUserId,ActionCode,Reason)
                      VALUES(:match,:match,:actor,'TIMER_CHANGED','DEACTIVATED')
                    """), {"match": current_match_id, "actor": user["user_id"]})
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


@router.put("/competition/combate-actual/cronometro")
async def configure_current_combat_timer(payload: MatchTimerConfig,
                                         user=Depends(require_roles(*STAFF))):
    snapshot = await asyncio.to_thread(_apply_match_timer_change, "configure", user, payload)
    await live_combat_connections.broadcast(snapshot)
    return snapshot


@router.post("/competition/combate-actual/cronometro/{action}")
async def control_current_combat_timer(action: str,
                                      user=Depends(require_roles(*STAFF))):
    if action not in {"start", "pause", "reset"}:
        raise HTTPException(404, "Operación de cronómetro no encontrada.")
    snapshot = await asyncio.to_thread(_apply_match_timer_change, action, user)
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
        snapshot = {"event_id": event_id, "status": state,
                    "items": [{k: v for k, v in item.items() if k != "updated_at"} for item in items]}
        tournament = db.execute(text("""
          SELECT TOP (1) CategoryId FROM dbo.TournamentPhaseState
          WHERE EventId=:event ORDER BY UpdatedAt DESC,CategoryId
        """), {"event": event_id}).scalar_one_or_none()
        if tournament is not None:
            snapshot["tournament"] = _tournament_snapshot(db,event_id,int(tournament))
        return snapshot
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
