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
TOURNAMENT_YUKOS_TO_WIN = 2
FINAL_YUKOS_TO_WIN = 3
TRANSITIONS = {"DRAFT": {"SCHEDULED", "CANCELLED"}, "SCHEDULED": {"LIVE", "CANCELLED"},
               "LIVE": {"PAUSED", "FINISHED", "CANCELLED"}, "PAUSED": {"LIVE", "FINISHED", "CANCELLED"},
               "FINISHED": set(), "CANCELLED": set()}


def can_transition(previous: str, target: str) -> bool:
    return target == previous or target in TRANSITIONS.get(previous, set())


def _yukos_to_win(stage: str) -> int:
    """The official final is first to three; every other tournament bout to two."""
    return FINAL_YUKOS_TO_WIN if stage == "FINAL" else TOURNAMENT_YUKOS_TO_WIN


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
    group_code: str = Field(min_length=1, max_length=20, pattern="^[A-Za-z0-9_-]+$")

    @field_validator("group_code")
    @classmethod
    def normalize_group_code(cls, value):
        return value.strip().upper()


class TournamentInitializeInput(BaseModel):
    category_id: int = Field(gt=0)
    teams: list[TournamentTeamAssignment] = Field(min_length=4, max_length=64)


class TournamentFromGroupsInput(BaseModel):
    category_id: int = Field(gt=0)


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


def _bracket_stage(team_count: int) -> str:
    if team_count <= 2:
        return "FINAL"
    bracket_size = 1 << (team_count - 1).bit_length()
    return {4: "SEMIFINAL", 8: "QUARTERFINAL", 16: "ROUND_OF_16",
            32: "ROUND_OF_32", 64: "ROUND_OF_64"}.get(bracket_size, "")


def _phase_label(stage: str) -> str:
    return {"GROUP": "Fase de grupos", "ROUND_OF_64": "Ronda de 64",
            "ROUND_OF_32": "Ronda de 32", "ROUND_OF_16": "Octavos de final",
            "QUARTERFINAL": "Cuartos de final", "SEMIFINAL": "Semifinales",
            "THIRD_PLACE": "Tercer puesto", "FINAL": "Gran final",
            "FINISHED": "Torneo finalizado"}.get(stage, stage.replace("_", " ").title())


def _rank_group_standings(group_teams: list[dict], matches: list[dict]) -> list[dict]:
    """Rank by wins, Yuko difference, then valid head-to-head results only."""
    for team in group_teams:
        team["difference"] = team["yukos_for"] - team["yukos_against"]
        team["tie_status"] = None
        team["tie_breaker"] = None
    tiers: dict[tuple[int, int], list[dict]] = {}
    for team in group_teams:
        tiers.setdefault((team["wins"], team["difference"]), []).append(team)

    ranked: list[dict] = []
    rank = 1
    for wins, difference in sorted(tiers, key=lambda item: (-item[0], -item[1])):
        tied = tiers[(wins, difference)]
        tied_ids = {team["team_id"] for team in tied}
        direct_results: dict[frozenset[int], list[int]] = {}
        for match in matches:
            left_id, right_id = match["team_id_a"], match["team_id_b"]
            if (match["stage_code"] != "GROUP" or match["status"] != "FINISHED"
                    or left_id not in tied_ids or right_id not in tied_ids
                    or match["winner_team_id"] not in (left_id, right_id)):
                continue
            pair = frozenset((left_id, right_id))
            direct_results.setdefault(pair, []).append(int(match["winner_team_id"]))

        resolved_order: list[dict] | None = None
        if len(tied) == 2:
            pair = frozenset(tied_ids)
            winners = direct_results.get(pair, [])
            if len(winners) == 1:
                resolved_order = sorted(tied, key=lambda team: team["team_id"] != winners[0])
        elif len(tied) > 2:
            ordered_ids = sorted(tied_ids)
            pairs = [frozenset((left, right)) for index, left in enumerate(ordered_ids)
                     for right in ordered_ids[index + 1:]]
            if pairs and all(len(direct_results.get(pair, [])) == 1 for pair in pairs):
                edges = {team_id: set() for team_id in tied_ids}
                for pair in pairs:
                    winner = direct_results[pair][0]
                    loser = next(team_id for team_id in pair if team_id != winner)
                    edges[winner].add(loser)
                remaining = set(tied_ids)
                ordered_ids = []
                while remaining:
                    unbeaten = [team_id for team_id in remaining
                                if not any(team_id in edges[other] for other in remaining if other != team_id)]
                    if len(unbeaten) != 1:
                        break
                    ordered_ids.append(unbeaten[0])
                    remaining.remove(unbeaten[0])
                if not remaining:
                    by_id = {team["team_id"]: team for team in tied}
                    resolved_order = [by_id[team_id] for team_id in ordered_ids]

        if resolved_order is not None:
            for offset, team in enumerate(resolved_order):
                team["rank"] = rank + offset
                team["tie_status"] = "RESOLVED"
                team["tie_breaker"] = "HEAD_TO_HEAD"
            ranked.extend(resolved_order)
        else:
            # TeamId is only a stable display order; all members retain the same official position.
            for team in sorted(tied, key=lambda item: item["team_id"]):
                team["rank"] = rank
                if len(tied) > 1:
                    team["tie_status"] = "UNRESOLVED"
                    team["tie_breaker"] = None
                ranked.append(team)
        rank += len(tied)
    group_teams[:] = ranked
    return group_teams


def _unresolved_qualifying_ties(groups: dict[str, list[dict]]) -> list[str]:
    """Groups whose unresolved tie crosses the top-two qualification boundary."""
    return [code for code, rows in groups.items()
            if any(row.get("tie_status") == "UNRESOLVED" and row["rank"] <= 2 for row in rows)]


def _phase_progress(matches: list[dict], phase: str | None) -> dict:
    stage = "FINAL" if phase == "FINISHED" else phase
    current = [match for match in matches if match["stage_code"] == stage] if stage else []
    counts = {status: sum(match["status"] == status for match in current)
              for status in ("FINISHED", "LIVE", "SCHEDULED", "CANCELLED")}
    total = len(current)
    return {"stage": stage, "total": total, "finished": counts["FINISHED"],
            "live": counts["LIVE"], "scheduled": counts["SCHEDULED"],
            "cancelled": counts["CANCELLED"], "remaining": total - counts["FINISHED"],
            "complete": total > 0 and counts["FINISHED"] == total}


def _next_phase(phase: str | None, group_codes: list[str]) -> str | None:
    """Return the next official stage without changing tournament state."""
    if phase == "GROUP":
        if set(group_codes) == {"A", "B", "C", "D"}:
            return "QUARTERFINAL"
        return _bracket_stage(len(group_codes) * 2)
    return {"ROUND_OF_64": "ROUND_OF_32", "ROUND_OF_32": "ROUND_OF_16",
            "ROUND_OF_16": "QUARTERFINAL", "QUARTERFINAL": "SEMIFINAL",
            "SEMIFINAL": "THIRD_PLACE", "THIRD_PLACE": "FINAL",
            "FINAL": "FINISHED"}.get(phase)


def _tournament_matches(db: Session, event_id: int, category_id: int) -> list[dict]:
    rows = db.execute(text("""
      SELECT m.MatchId AS match_id,m.MatchNumber AS match_number,m.MatchStatus AS status,
        m.StageCode AS stage_code,m.GroupCode AS group_code,m.DohyoNumber AS dohyo_number,
        m.ScoreToWin AS score_to_win,m.BracketSlot AS bracket_slot,
        m.WinnerTeamId AS winner_team_id,m.LoserTeamId AS loser_team_id,
        tg.GroupName AS group_name,
        cr.RoundNumber AS schedule_round,cr.Name AS round_name,
        ta.TeamId AS team_id_a,ta.Name AS team_a,ia.Name AS institution_a,
        mtA.RobotId AS robot_id_a,ra.Name AS robot_a,
        COALESCE(sa.Points,0) AS score_a,
        tb.TeamId AS team_id_b,tb.Name AS team_b,ib.Name AS institution_b,
        mtB.RobotId AS robot_id_b,rb.Name AS robot_b,
        COALESCE(sb.Points,0) AS score_b
      FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      LEFT JOIN dbo.TournamentGroups tg ON tg.TournamentGroupId=m.TournamentGroupId
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
      ORDER BY cr.RoundNumber,m.MatchNumber
    """), {"event": event_id, "category": category_id}).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        for field in ("team_a", "team_b", "robot_a", "robot_b"):
            if item[field] is not None:
                item[field] = decrypt_text(item[field])
        item["score_a"] = int(item["score_a"] or 0)
        item["score_b"] = int(item["score_b"] or 0)
        # Expose the official threshold, correcting stale stored targets.
        item["score_to_win"] = _yukos_to_win(item["stage_code"])
        result.append(item)
    return result


def _tournament_snapshot(db: Session, event_id: int, category_id: int) -> dict:
    state = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one_or_none()
    configured_groups = db.execute(text("""
      SELECT TournamentGroupId AS group_id,GroupCode AS group_code,GroupName AS group_name,
        MaxTeams AS max_teams
      FROM dbo.TournamentGroups WHERE EventId=:event AND CategoryId=:category
      ORDER BY GroupCode,TournamentGroupId
    """), {"event": event_id, "category": category_id}).mappings().all()
    assignments = db.execute(text("""
      SELECT tg.GroupCode AS group_code,tg.GroupName AS group_name,t.TeamId AS team_id,t.Name AS team,
        i.Name AS institution,r.RobotId AS robot_id,r.Name AS robot
      FROM dbo.TournamentGroupRegistrations a
      JOIN dbo.TournamentGroups tg ON tg.TournamentGroupId=a.TournamentGroupId
      JOIN dbo.Registrations reg ON reg.RegistrationId=a.RegistrationId
      JOIN dbo.RegistrationStatuses st ON st.StatusId=reg.StatusId AND st.Code='APPROVED'
      JOIN dbo.Teams t ON t.TeamId=reg.TeamId JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      JOIN dbo.Robots r ON r.RobotId=reg.RobotId
      WHERE tg.EventId=:event AND tg.CategoryId=:category
      ORDER BY tg.GroupCode,t.Name,t.TeamId
    """), {"event": event_id, "category": category_id}).mappings().all()
    if not assignments:
      assignments = db.execute(text("""
      SELECT g.GroupCode AS group_code,t.TeamId AS team_id,t.Name AS team,
        i.Name AS institution,r.RobotId AS robot_id,r.Name AS robot
      FROM dbo.TournamentTeamGroups g
      JOIN dbo.Teams t ON t.TeamId=g.TeamId JOIN dbo.Institutions i ON i.InstitutionId=t.InstitutionId
      JOIN dbo.Robots r ON r.RobotId=g.RobotId
      WHERE g.EventId=:event AND g.CategoryId=:category
      ORDER BY g.GroupCode,t.Name,t.TeamId
      """), {"event": event_id, "category": category_id}).mappings().all()
    group_codes = [str(row["group_code"]) for row in configured_groups]
    if not group_codes:
        group_codes = sorted({str(row["group_code"]) for row in assignments})
    teams_by_group: dict[str, list[dict]] = {code: [] for code in group_codes}
    group_names = {str(row["group_code"]): str(row["group_name"]) for row in configured_groups}
    team_rows = {}
    for row in assignments:
        team = dict(row)
        team["team"] = decrypt_text(team["team"])
        team["robot"] = decrypt_text(team["robot"])
        team["group_name"] = team.get("group_name") or group_names.get(team["group_code"], f"Grupo {team['group_code']}")
        team.update({"played": 0, "wins": 0, "losses": 0, "points": 0,
                     "yukos_for": 0, "yukos_against": 0})
        teams_by_group[team["group_code"]].append(team)
        team_rows[team["team_id"]] = team

    matches = _tournament_matches(db, event_id, category_id)
    _accumulate_group_results(team_rows, matches)

    for group_teams in teams_by_group.values():
        _rank_group_standings(group_teams, matches)

    live_rows = db.execute(text("""
      SELECT DohyoNumber AS dohyo_number,MatchId AS match_id
      FROM dbo.LiveDohyoMatches WHERE EventId=:event AND CategoryId=:category
      ORDER BY DohyoNumber
    """), {"event": event_id, "category": category_id}).mappings().all()
    by_id = {match["match_id"]: match for match in matches}
    boards = [{"dohyo_number": number, "match": None} for number in range(1, 5)]
    for row in live_rows:
        boards[int(row["dohyo_number"]) - 1]["match"] = by_id.get(row["match_id"])
    progress = _phase_progress(matches, state)
    unresolved_ties = (_unresolved_qualifying_ties(teams_by_group)
                       if state == "GROUP" and progress["complete"] else [])
    phase = state or "NOT_CONFIGURED"
    next_phase = _next_phase(phase, group_codes)
    can_advance = (progress["complete"] and phase not in ("NOT_CONFIGURED", "FINISHED")
                   and not unresolved_ties and next_phase is not None)
    return {"event_id": event_id, "category_id": category_id, "phase": phase,
            "groups": teams_by_group, "group_names": group_names, "matches": matches, "boards": boards,
            "unresolved_qualifying_ties": unresolved_ties, "phase_progress": progress,
            "next_phase": next_phase, "can_advance": can_advance}


def _accumulate_group_results(team_rows: dict[int, dict], matches: list[dict]) -> None:
    """Count one win per finished fixture and include only its official Yuko total."""
    for match in matches:
        if match["stage_code"] != "GROUP" or match["status"] != "FINISHED":
            continue
        left = team_rows.get(match["team_id_a"])
        right = team_rows.get(match["team_id_b"])
        if not left or not right:
            continue
        left["played"] += 1
        right["played"] += 1
        left["yukos_for"] += match["score_a"]
        left["yukos_against"] += match["score_b"]
        right["yukos_for"] += match["score_b"]
        right["yukos_against"] += match["score_a"]
        if match["winner_team_id"] == left["team_id"]:
            left["wins"] += 1
            left["points"] += 3
            right["losses"] += 1
        elif match["winner_team_id"] == right["team_id"]:
            right["wins"] += 1
            right["points"] += 3
            left["losses"] += 1


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
                             score_to_win: int = 2, group_id: int | None = None) -> int:
    # Keep phase thresholds consistent even if a caller passes a legacy target.
    score_to_win = _yukos_to_win(stage)
    match_id = int(db.execute(text("""
      INSERT dbo.CompetitionMatches(RoundId,MatchNumber,MatchStatus,StageCode,GroupCode,
        DohyoNumber,ScoreToWin,BracketSlot,TournamentGroupId)
      OUTPUT INSERTED.MatchId
      VALUES(:round,:number,'SCHEDULED',:stage,:group,:dohyo,:target,:slot,:group_id)
    """), {"round": round_id, "number": match_number, "stage": stage,
          "group": group_code, "dohyo": dohyo, "target": score_to_win, "slot": slot,
          "group_id": group_id}).scalar_one())
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
                        fixtures: list[tuple[int, str, list[int], int]], actor_id: int,
                        byes: list[dict] | None = None) -> list[int]:
    round_id = _ensure_tournament_round(db, event_id, category_id, _phase_label(stage), actor_id)
    matches = []
    for number, (_requested_dohyo, slot, team_ids, score_to_win) in enumerate(fixtures, 1):
        dohyo = ((number - 1) % 4) + 1
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
        if number <= 4:
            db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:id"),
                       {"id": match_id})
            _set_live_dohyo(db,event_id,category_id,dohyo,match_id,actor_id)
        matches.append(match_id)
    for bye in byes or []:
        db.execute(text("""
          INSERT dbo.TournamentBracketByes(EventId,CategoryId,StageCode,TeamId,RobotId,SeedNumber)
          VALUES(:event,:category,:stage,:team,:robot,:seed)
        """), {"event": event_id, "category": category_id, "stage": stage,
              "team": bye["team_id"], "robot": bye["robot_id"], "seed": bye["seed"]})
    if matches:
        _set_primary_live_match(db,matches[0],actor_id)
    return matches


def _make_seeded_fixtures(stage: str, seeded_teams: list[dict], actor_id: int,
                          *, score_to_win: int = 2):
    """Pair seeded entrants while avoiding a first-round rematch from one group."""
    score_to_win = _yukos_to_win(stage)
    count = len(seeded_teams)
    bracket_size = 1 << (count - 1).bit_length()
    bye_count = bracket_size - count
    byes = [{**item, "seed": index + 1} for index, item in enumerate(seeded_teams[:bye_count])]
    remaining = list(seeded_teams[bye_count:])
    fixtures = []
    round_label = {"ROUND_OF_64": 64, "ROUND_OF_32": 32, "ROUND_OF_16": 16,
                   "QUARTERFINAL": 8, "SEMIFINAL": 4}.get(stage, bracket_size)
    while remaining:
        left = remaining.pop(0)
        opponent_index = next((index for index in range(len(remaining) - 1, -1, -1)
                               if remaining[index].get("group_code") != left.get("group_code")),
                              len(remaining) - 1)
        right = remaining.pop(opponent_index)
        number = len(fixtures) + 1
        slot = f"R{round_label}-M{number}"
        fixtures.append((number, slot, [left["team_id"], right["team_id"]], score_to_win))
    return fixtures, byes


def _next_group_match(db: Session, event_id: int, category_id: int,
                      group_code: str, dohyo_number: int) -> int | None:
    """Get the next ready fixture in this group's fixed dohyo lane."""
    return db.execute(text("""
      SELECT TOP (1) candidate.MatchId
      FROM dbo.CompetitionMatches candidate
      JOIN dbo.CompetitionRounds candidate_round ON candidate_round.RoundId=candidate.RoundId
      WHERE candidate_round.EventId=:event AND candidate_round.CategoryId=:category
        AND candidate.StageCode='GROUP' AND candidate.MatchStatus='SCHEDULED'
        AND candidate.GroupCode=:group_code
        AND candidate.DohyoNumber=:dohyo
        AND NOT EXISTS (
          SELECT 1 FROM dbo.CompetitionMatches prior
          JOIN dbo.CompetitionRounds prior_round ON prior_round.RoundId=prior.RoundId
          WHERE prior_round.EventId=:event AND prior_round.CategoryId=:category
            AND prior.StageCode='GROUP' AND prior.GroupCode=:group_code
            AND prior_round.RoundNumber<candidate_round.RoundNumber
            AND prior.MatchStatus<>'FINISHED'
        )
        AND candidate_round.RoundNumber=(
          SELECT MIN(open_round.RoundNumber)
          FROM dbo.CompetitionMatches open_match
          JOIN dbo.CompetitionRounds open_round ON open_round.RoundId=open_match.RoundId
          WHERE open_round.EventId=:event AND open_round.CategoryId=:category
            AND open_match.StageCode='GROUP' AND open_match.GroupCode=:group_code
            AND open_match.MatchStatus<>'FINISHED'
        )
        AND NOT EXISTS (
          SELECT 1 FROM dbo.LiveDohyoMatches live
          JOIN dbo.CompetitionMatches active_match ON active_match.MatchId=live.MatchId
          JOIN dbo.CompetitionMatchTeams active_team ON active_team.MatchId=active_match.MatchId
          JOIN dbo.CompetitionMatchTeams candidate_team ON candidate_team.MatchId=candidate.MatchId
            AND candidate_team.TeamId=active_team.TeamId
          WHERE live.EventId=:event AND live.CategoryId=:category
            AND active_match.MatchStatus='LIVE'
        )
      ORDER BY candidate_round.RoundNumber,candidate.GroupCode,candidate.MatchNumber
    """), {"event": event_id, "category": category_id, "dohyo": dohyo_number,
            "group_code": group_code}).scalar_one_or_none()


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
    if phase == "GROUP":
        snapshot = _tournament_snapshot(db,event_id,category_id)
        groups = snapshot["groups"]
        group_codes = sorted(groups)
        if len(group_codes) < 2 or any(len(groups[code]) < 2 for code in group_codes):
            raise HTTPException(409, "Se requieren al menos dos grupos y dos equipos aprobados en cada grupo.")
        if snapshot["unresolved_qualifying_ties"]:
            # Keep the completed results and phase intact; never promote a team
            # selected only by the technical display order when the rules tie.
            return
        # Preserve the Thursday bracket only for the official A-D group codes.
        # Four custom groups still use the generic seeded bracket below.
        if set(group_codes) == {"A", "B", "C", "D"}:
            formulas = [(1,"QF1",groups["A"][0]["team_id"],groups["B"][1]["team_id"]),
                        (2,"QF2",groups["C"][0]["team_id"],groups["D"][1]["team_id"]),
                        (3,"QF3",groups["B"][0]["team_id"],groups["A"][1]["team_id"]),
                        (4,"QF4",groups["D"][0]["team_id"],groups["C"][1]["team_id"])]
            fixtures = [(dohyo,slot,[left,right],2) for dohyo,slot,left,right in formulas]
            next_phase = "QUARTERFINAL"
            byes = []
        else:
            seeded = []
            # Group champions are seeded first; second place teams follow in reverse group order.
            for code in group_codes:
                team = groups[code][0]
                seeded.append({"team_id": team["team_id"], "robot_id": team["robot_id"], "group_code": code})
            for code in reversed(group_codes):
                team = groups[code][1]
                seeded.append({"team_id": team["team_id"], "robot_id": team["robot_id"], "group_code": code})
            next_phase = _bracket_stage(len(seeded))
            if not next_phase:
                raise HTTPException(422, "La cantidad de clasificados supera el máximo de 64 equipos.")
            fixtures, byes = _make_seeded_fixtures(next_phase, seeded, actor_id)
        _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id,byes)
        db.execute(text("""
          UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,UpdatedByUserId=:actor,
            UpdatedAt=SYSUTCDATETIME() WHERE EventId=:event AND CategoryId=:category
        """), {"phase": next_phase, "actor": actor_id, "event": event_id, "category": category_id})
        return
    elif phase == "SEMIFINAL":
        results = [row for row in _tournament_matches(db,event_id,category_id)
                   if row["stage_code"] == "SEMIFINAL"]
        if len(results) != 2 or any(not row["loser_team_id"] for row in results):
            raise HTTPException(409, "No se puede formar el combate por el tercer puesto: faltan resultados de semifinales.")
        fixtures = [(1,"THIRD",[results[0]["loser_team_id"],results[1]["loser_team_id"]],2)]
        next_phase = "THIRD_PLACE"
        _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id)
        db.execute(text("""UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,
          UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE EventId=:event AND CategoryId=:category"""),
          {"phase": next_phase, "actor": actor_id, "event": event_id, "category": category_id})
        return
    elif phase == "THIRD_PLACE":
        results = [row for row in _tournament_matches(db,event_id,category_id)
                   if row["stage_code"] == "SEMIFINAL"]
        if len(results) != 2 or any(not row["winner_team_id"] for row in results):
            raise HTTPException(409, "No se puede formar la final: faltan resultados de semifinales.")
        fixtures = [(1,"FINAL",[results[0]["winner_team_id"],results[1]["winner_team_id"]],FINAL_YUKOS_TO_WIN)]
        next_phase = "FINAL"
        _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id)
        db.execute(text("""UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,
          UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE EventId=:event AND CategoryId=:category"""),
          {"phase": next_phase, "actor": actor_id, "event": event_id, "category": category_id})
        return
    elif phase == "FINAL":
        db.execute(text("""
          UPDATE dbo.TournamentPhaseState SET CurrentPhase='FINISHED',UpdatedByUserId=:actor,
            UpdatedAt=SYSUTCDATETIME() WHERE EventId=:event AND CategoryId=:category
        """), {"actor": actor_id, "event": event_id, "category": category_id})
        return

    # Knockout rounds beyond the first: winners and previously awarded byes
    # advance; any remaining unequal seed is paired with a different group
    # where possible. A two-match semifinal preserves the Thursday bronze/final path.
    results = [row for row in _tournament_matches(db,event_id,category_id)
               if row["stage_code"] == phase]
    advancing = [{"team_id": row["winner_team_id"], "robot_id": row["robot_id_a"]
                  if row["winner_team_id"] == row["team_id_a"] else row["robot_id_b"],
                  "group_code": None} for row in results if row["winner_team_id"]]
    bye_rows = db.execute(text("""
      SELECT TeamId AS team_id,RobotId AS robot_id,SeedNumber AS seed
      FROM dbo.TournamentBracketByes WHERE EventId=:event AND CategoryId=:category AND StageCode=:stage
      ORDER BY SeedNumber
    """), {"event": event_id, "category": category_id, "stage": phase}).mappings().all()
    advancing.extend({"team_id": int(row["team_id"]), "robot_id": int(row["robot_id"]), "group_code": None}
                     for row in bye_rows)
    db.execute(text("""DELETE dbo.TournamentBracketByes
      WHERE EventId=:event AND CategoryId=:category AND StageCode=:stage"""),
      {"event": event_id, "category": category_id, "stage": phase})
    if len(advancing) <= 1:
        db.execute(text("""UPDATE dbo.TournamentPhaseState SET CurrentPhase='FINISHED',
          UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
          WHERE EventId=:event AND CategoryId=:category"""),
          {"actor": actor_id, "event": event_id, "category": category_id})
        return
    if len(advancing) == 4:
        if phase == "QUARTERFINAL":
            # Thursday's official path: QF1 vs QF2, then QF3 vs QF4.
            quarterfinal_winners = {row["bracket_slot"]: row["winner_team_id"] for row in results}
            if all(quarterfinal_winners.get(slot) for slot in ("QF1", "QF2", "QF3", "QF4")):
                semifinal_pairs = [(quarterfinal_winners["QF1"], quarterfinal_winners["QF2"]),
                                   (quarterfinal_winners["QF3"], quarterfinal_winners["QF4"])]
            else:
                semifinal_pairs = [(advancing[0]["team_id"], advancing[3]["team_id"]),
                                   (advancing[1]["team_id"], advancing[2]["team_id"])]
        else:
            semifinal_pairs = [(advancing[0]["team_id"], advancing[3]["team_id"]),
                               (advancing[1]["team_id"], advancing[2]["team_id"])]
        fixtures = [(index, f"SF{index}", list(pair), 2)
                    for index, pair in enumerate(semifinal_pairs, 1)]
        next_phase = "SEMIFINAL"
        _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id)
    elif len(advancing) == 2:
        next_phase = "FINAL"
        _create_match_batch(db,event_id,category_id,next_phase,
                            [(1,"FINAL",[advancing[0]["team_id"],advancing[1]["team_id"]],FINAL_YUKOS_TO_WIN)],actor_id)
    else:
        next_phase = _bracket_stage(len(advancing))
        if not next_phase:
            raise HTTPException(422,"La ronda eliminatoria supera el máximo de 64 equipos.")
        # Entrants here have no same-group constraint remaining; keep the seed order.
        fixtures, byes = _make_seeded_fixtures(next_phase, advancing, actor_id)
        _create_match_batch(db,event_id,category_id,next_phase,fixtures,actor_id,byes)
    db.execute(text("""UPDATE dbo.TournamentPhaseState SET CurrentPhase=:phase,
      UpdatedByUserId=:actor,UpdatedAt=SYSUTCDATETIME()
      WHERE EventId=:event AND CategoryId=:category"""),
      {"phase": next_phase, "actor": actor_id, "event": event_id, "category": category_id})


@router.get("/events/{event_id}/tournament")
def get_tournament(event_id: int, category_id: int = Query(gt=0),
                   user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:event"), {"event": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    return _tournament_snapshot(db,event_id,category_id)


def _advance_tournament_phase(db: Session, event_id: int, category_id: int,
                              actor_id: int) -> dict:
    """Lock and advance exactly one completed phase inside the caller's transaction."""
    locked_phase = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one_or_none()
    if locked_phase is None:
        raise HTTPException(404, "No existe un torneo configurado para esta categoría.")
    snapshot = _tournament_snapshot(db, event_id, category_id)
    if snapshot["phase"] == "FINISHED":
        raise HTTPException(409, "El torneo ya finalizó.")
    if not snapshot["phase_progress"]["complete"]:
        progress = snapshot["phase_progress"]
        raise HTTPException(409,
            f"La fase aún tiene {progress['remaining']} encuentro(s) sin finalizar.")
    current_results = [match for match in snapshot["matches"]
                       if match["stage_code"] == snapshot["phase"]]
    if any(match["status"] != "FINISHED" or not match["winner_team_id"]
           for match in current_results):
        raise HTTPException(409,
            "No se puede avanzar: faltan resultados oficiales completos en esta fase.")
    if snapshot["unresolved_qualifying_ties"]:
        raise HTTPException(409,
            "No se puede avanzar: hay empates de clasificación que requieren resolución.")
    if not snapshot["next_phase"]:
        raise HTTPException(409, "No se pudo determinar la siguiente fase del torneo.")
    _progress_tournament(db, event_id, category_id, actor_id)
    result = _tournament_snapshot(db, event_id, category_id)
    if result["phase"] == snapshot["phase"]:
        raise HTTPException(409, "El torneo no pudo avanzar; revise la configuración y los resultados.")
    return result


@router.post("/events/{event_id}/tournament/advance-phase")
async def advance_tournament_phase(event_id: int, category_id: int = Query(gt=0),
                                  user=Depends(require_roles(*STAFF))):
    """Advance exactly one completed phase, explicitly requested by tournament staff."""
    def apply():
        db = SessionLocal()
        try:
            result = _advance_tournament_phase(db, event_id, category_id, user["user_id"])
            db.commit()
            return result
        except HTTPException:
            db.rollback()
            raise
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "La fase no pudo avanzar por un conflicto con el calendario.")
        finally:
            db.close()

    tournament = await asyncio.to_thread(apply)
    # The public live snapshot reads SQL every two seconds; this immediate
    # broadcast updates the current-combat channel for connected screens too.
    await live_combat_connections.broadcast(await asyncio.to_thread(_load_current_combat_snapshot))
    return tournament


@router.post("/events/{event_id}/tournament")
def initialize_tournament(event_id: int, payload: TournamentInitializeInput,
                          user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if not db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:event"), {"event": event_id}).first():
        raise HTTPException(404, "Evento no encontrado.")
    if not db.execute(text("""
      SELECT 1 FROM dbo.EventCategories WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": payload.category_id}).first():
        raise HTTPException(422, "La categoría no pertenece a este evento.")
    group_codes = sorted({team.group_code for team in payload.teams})
    if len(group_codes) < 2 or len(group_codes) > 32:
        raise HTTPException(422, "El torneo requiere entre 2 y 32 grupos configurados.")
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
        if any(len(group_teams) < 2 for group_teams in assigned.values()):
            raise HTTPException(422, "Cada grupo necesita al menos dos equipos para generar encuentros.")

        queues = {code: _round_robin_pairs(assigned[code]) for code in group_codes}
        frame_count = max(len(queue) for queue in queues.values())
        robots = {item.team_id: item.robot_id for item in payload.teams}
        group_ids = {str(row.GroupCode): int(row.TournamentGroupId) for row in db.execute(text("""
          SELECT TournamentGroupId,GroupCode FROM dbo.TournamentGroups
          WHERE EventId=:event AND CategoryId=:category
        """), {"event": event_id, "category": payload.category_id}).all()}
        for frame in range(frame_count):
            round_id = _ensure_tournament_round(db,event_id,payload.category_id,
                                                 f"Grupos · Jornada {frame+1}",user["user_id"])
            for group_index, code in enumerate(group_codes):
                if frame >= len(queues[code]):
                    continue
                left, right = queues[code][frame]
                dohyo = (group_index % 4) + 1
                _create_tournament_match(db,event_id,payload.category_id,round_id,dohyo,
                    "GROUP",dohyo,[(left,robots[left]),(right,robots[right])],user["user_id"],
                    group_code=code,score_to_win=2,group_id=group_ids.get(code))
        db.execute(text("""
          INSERT dbo.TournamentPhaseState(EventId,CategoryId,CurrentPhase,CreatedByUserId,UpdatedByUserId)
          VALUES(:event,:category,'GROUP',:actor,:actor)
        """), {"event": event_id, "category": payload.category_id, "actor": user["user_id"]})
        db.commit()
        return _tournament_snapshot(db,event_id,payload.category_id)
    except HTTPException:
        db.rollback()
        raise


@router.post("/events/{event_id}/tournament/from-groups")
def initialize_tournament_from_groups(event_id: int, payload: TournamentFromGroupsInput,
                                      user=Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    """Build a non-repeating round robin from the event's saved group assignments."""
    if not db.execute(text("""SELECT 1 FROM dbo.EventCategories
      WHERE EventId=:event AND CategoryId=:category"""),
      {"event": event_id, "category": payload.category_id}).first():
        raise HTTPException(422, "La categoría no pertenece a este evento.")
    try:
        existing = db.execute(text("""SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
          WHERE EventId=:event AND CategoryId=:category"""),
          {"event": event_id, "category": payload.category_id}).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "El calendario de esta categoría ya fue generado.")
        groups = db.execute(text("""
          SELECT TournamentGroupId AS group_id,GroupCode AS group_code,GroupName AS group_name,MaxTeams AS max_teams
          FROM dbo.TournamentGroups WITH (UPDLOCK,HOLDLOCK)
          WHERE EventId=:event AND CategoryId=:category ORDER BY GroupCode
        """), {"event": event_id, "category": payload.category_id}).mappings().all()
        if not 2 <= len(groups) <= 32:
            raise HTTPException(422, "Configura entre 2 y 32 grupos para el evento y la categoría.")
        assigned: dict[str, list[tuple[int, int, int]]] = {
            str(group["group_code"]): [] for group in groups}
        for group in groups:
            rows = db.execute(text("""
              SELECT r.RegistrationId AS registration_id,r.TeamId AS team_id,r.RobotId AS robot_id
              FROM dbo.TournamentGroupRegistrations a WITH (UPDLOCK,HOLDLOCK)
              JOIN dbo.Registrations r ON r.RegistrationId=a.RegistrationId
              JOIN dbo.RegistrationStatuses st ON st.StatusId=r.StatusId AND st.Code='APPROVED'
              WHERE a.TournamentGroupId=:group AND r.EventId=:event AND r.CategoryId=:category
              ORDER BY r.RegistrationId
            """), {"group": group["group_id"], "event": event_id,
                  "category": payload.category_id}).mappings().all()
            if len(rows) < 2:
                raise HTTPException(422, f"El {group['group_name']} necesita al menos dos equipos aprobados.")
            if len(rows) > int(group["max_teams"]):
                raise HTTPException(409, f"El {group['group_name']} supera su capacidad máxima.")
            assigned[str(group["group_code"])] = [
                (int(row["registration_id"]), int(row["team_id"]), int(row["robot_id"])) for row in rows]
        all_teams = [team for rows in assigned.values() for team in rows]
        if len({item[1] for item in all_teams}) != len(all_teams) or len({item[2] for item in all_teams}) != len(all_teams):
            raise HTTPException(409, "Hay equipos o robots repetidos entre las asignaciones.")

        # Keep the legacy team/robot lookup synchronized for knockout matches.
        for group in groups:
            for _, team_id, robot_id in assigned[str(group["group_code"])]:
                prior = db.execute(text("""SELECT RobotId,GroupCode FROM dbo.TournamentTeamGroups
                  WITH (UPDLOCK,HOLDLOCK) WHERE EventId=:event AND CategoryId=:category AND TeamId=:team"""),
                  {"event": event_id, "category": payload.category_id, "team": team_id}).first()
                if prior:
                    if int(prior.RobotId) != robot_id or str(prior.GroupCode).strip() != str(group["group_code"]):
                        raise HTTPException(409, "La asignación guardada de un equipo no coincide con su grupo actual.")
                    continue
                db.execute(text("""INSERT dbo.TournamentTeamGroups
                  (EventId,CategoryId,TeamId,RobotId,GroupCode,AssignedByUserId)
                  VALUES(:event,:category,:team,:robot,:code,:actor)"""),
                  {"event": event_id, "category": payload.category_id, "team": team_id,
                   "robot": robot_id, "code": group["group_code"], "actor": user["user_id"]})

        group_codes = sorted(assigned)
        queues = {code: _round_robin_pairs([team_id for _, team_id, _ in assigned[code]])
                  for code, rows in assigned.items()}
        robots = {team_id: robot_id for group in groups
                  for _, team_id, robot_id in assigned[str(group["group_code"])]}
        frame_count = max(map(len, queues.values()))
        group_ids = {str(item["group_code"]): int(item["group_id"]) for item in groups}
        for frame in range(frame_count):
            round_id = _ensure_tournament_round(db,event_id,payload.category_id,
                f"Grupos · Jornada {frame+1}",user["user_id"])
            for group_index, code in enumerate(group_codes):
                if frame >= len(queues[code]):
                    continue
                left, right = queues[code][frame]
                dohyo = (group_index % 4) + 1
                _create_tournament_match(db,event_id,payload.category_id,round_id,dohyo,"GROUP",dohyo,
                    [(left,robots[left]),(right,robots[right])],user["user_id"],
                    group_code=code,score_to_win=2,group_id=group_ids[code])
        db.execute(text("""INSERT dbo.TournamentPhaseState
          (EventId,CategoryId,CurrentPhase,CreatedByUserId,UpdatedByUserId)
          VALUES(:event,:category,'GROUP',:actor,:actor)"""),
          {"event": event_id, "category": payload.category_id, "actor": user["user_id"]})
        db.commit()
        return _tournament_snapshot(db,event_id,payload.category_id)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo crear el calendario; revise las asignaciones y los encuentros existentes.")
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
            first_candidates = db.execute(text("""
              SELECT m.MatchId AS match_id,ta.TeamId AS team_a,tb.TeamId AS team_b
              FROM dbo.CompetitionMatches m
              JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
              JOIN dbo.CompetitionMatchTeams ta ON ta.MatchId=m.MatchId AND ta.TeamPosition=1
              JOIN dbo.CompetitionMatchTeams tb ON tb.MatchId=m.MatchId AND tb.TeamPosition=2
              WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode='GROUP'
                AND m.MatchStatus='SCHEDULED'
                AND r.RoundNumber=(SELECT MIN(r2.RoundNumber) FROM dbo.CompetitionMatches m2
                  JOIN dbo.CompetitionRounds r2 ON r2.RoundId=m2.RoundId
                  WHERE r2.EventId=:event AND r2.CategoryId=:category AND m2.StageCode='GROUP'
                    AND m2.MatchStatus<>'FINISHED')
              ORDER BY m.GroupCode,m.MatchNumber
            """), {"event": event_id, "category": category_id}).mappings().all()
            first_ids = []
            occupied_teams = set()
            for candidate in first_candidates:
                pair = {int(candidate["team_a"]), int(candidate["team_b"])}
                if pair & occupied_teams:
                    continue
                first_ids.append(int(candidate["match_id"]))
                occupied_teams.update(pair)
                if len(first_ids) == 4:
                    break
            for dohyo, match_id in enumerate(first_ids, 1):
                db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:id"),
                           {"id": match_id})
                _set_live_dohyo(db,event_id,category_id,dohyo,int(match_id),user["user_id"])
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


@router.post("/events/{event_id}/tournament/matches/{match_id}/start")
def start_selected_tournament_match(
    event_id: int,
    match_id: int,
    category_id: int = Query(gt=0),
    dohyo_number: int = Query(ge=1, le=4),
    user=Depends(require_roles(*STAFF)),
    db: Session = Depends(get_db),
):
    """Let staff choose the next valid group fixture and its display dohyo."""
    phase = db.execute(text("""
      SELECT CurrentPhase FROM dbo.TournamentPhaseState WITH (UPDLOCK,HOLDLOCK)
      WHERE EventId=:event AND CategoryId=:category
    """), {"event": event_id, "category": category_id}).scalar_one_or_none()
    if phase is None or phase == "FINISHED":
        raise HTTPException(409, "El calendario no está listo para iniciar encuentros.")
    match = db.execute(text("""
      SELECT m.MatchId,m.MatchStatus,m.StageCode,m.GroupCode,m.DohyoNumber,r.RoundNumber
      FROM dbo.CompetitionMatches m WITH (UPDLOCK,HOLDLOCK)
      JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE m.MatchId=:match AND r.EventId=:event AND r.CategoryId=:category
    """), {"match": match_id, "event": event_id, "category": category_id}).mappings().first()
    if match is None:
        raise HTTPException(404, "El encuentro no pertenece a este evento y categoría.")
    if match["MatchStatus"] != "SCHEDULED" or match["StageCode"] != phase:
        raise HTTPException(409, "Solo puede iniciar un encuentro programado de la fase actual.")
    if phase == "GROUP":
        if int(match["DohyoNumber"]) != dohyo_number:
            raise HTTPException(409, f"Este grupo está asignado al Dohyo {match['DohyoNumber']}; debe continuar en ese mismo dohyo.")
        earlier_pending = db.execute(text("""
          SELECT TOP (1) 1 FROM dbo.CompetitionMatches prior
          JOIN dbo.CompetitionRounds prior_round ON prior_round.RoundId=prior.RoundId
          WHERE prior_round.EventId=:event AND prior_round.CategoryId=:category
            AND prior.StageCode='GROUP' AND prior.GroupCode=:group
            AND prior_round.RoundNumber<:round AND prior.MatchStatus<>'FINISHED'
        """), {"event": event_id, "category": category_id, "group": match["GroupCode"],
              "round": match["RoundNumber"]}).first()
        if earlier_pending:
            raise HTTPException(409, "Termina primero el combate anterior de este grupo.")
    lane = db.execute(text("""
      SELECT m.MatchStatus FROM dbo.LiveDohyoMatches l
      JOIN dbo.CompetitionMatches m ON m.MatchId=l.MatchId
      WHERE l.EventId=:event AND l.CategoryId=:category AND l.DohyoNumber=:dohyo
    """), {"event": event_id, "category": category_id, "dohyo": dohyo_number}).scalar_one_or_none()
    if lane == "LIVE":
        raise HTTPException(409, "Ese dohyo ya tiene un combate en curso.")
    team_ids = [int(value) for value in db.execute(text("""
      SELECT TeamId FROM dbo.CompetitionMatchTeams WHERE MatchId=:match
      ORDER BY TeamPosition
    """), {"match": match_id}).scalars().all()]
    if len(team_ids) != 2:
        raise HTTPException(409, "El encuentro debe tener exactamente dos equipos.")
    overlap = db.execute(text("""
      SELECT TOP (1) 1
      FROM dbo.LiveDohyoMatches l
      JOIN dbo.CompetitionMatches active ON active.MatchId=l.MatchId AND active.MatchStatus='LIVE'
      JOIN dbo.CompetitionMatchTeams active_team ON active_team.MatchId=active.MatchId
      WHERE l.EventId=:event AND l.CategoryId=:category AND active_team.TeamId IN (:left,:right)
    """), {"event": event_id, "category": category_id,
            "left": team_ids[0], "right": team_ids[1]}).first()
    if overlap:
        raise HTTPException(409, "Uno de esos equipos ya está combatiendo en otro dohyo.")
    active = db.execute(text("""
      SELECT m.MatchStatus,m.StageCode FROM dbo.ActiveCombat a
      JOIN dbo.CompetitionMatches m ON m.MatchId=a.MatchId WHERE a.ActiveCombatId=1
    """)).first()
    if active and active.StageCode == "MANUAL" and active.MatchStatus == "LIVE":
        raise HTTPException(409, "Finalice el combate manual activo antes de iniciar este encuentro.")

    db.execute(text("UPDATE dbo.CompetitionMatches SET MatchStatus='LIVE' WHERE MatchId=:match"),
               {"match": match_id})
    _write_event_status(db, event_id, "LIVE", user["user_id"],
                        f"Inicio de {match['GroupCode'] or match['StageCode']} · encuentro {match_id}")
    _set_live_dohyo(db, event_id, category_id, dohyo_number, match_id, user["user_id"])
    _set_primary_live_match(db, match_id, user["user_id"])
    db.commit()
    _broadcast_active_combat_if(db, event_id=event_id, match_id=match_id)
    return _tournament_snapshot(db, event_id, category_id)


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
            if match["MatchStatus"] != "LIVE" or match["CompetitionStatus"]!="LIVE":
                raise HTTPException(409,"El encuentro ya finalizó o no está en vivo; no se puede cambiar su puntuación.")
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
            target = _yukos_to_win(match["StageCode"])
            if payload.points_delta > 0 and totals[payload.team_id]>=target:
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
            if payload.points_delta > 0 and totals[payload.team_id]>=target:
                loser=next(team for team in teams if team!=payload.team_id)
                db.execute(text("""
                  UPDATE dbo.CompetitionMatches SET MatchStatus='FINISHED',WinnerTeamId=:winner,
                    LoserTeamId=:loser WHERE MatchId=:match
                """), {"winner":payload.team_id,"loser":loser,"match":match_id})
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
            if current["StageCode"] == "GROUP":
                next_match = _next_group_match(
                    db,event_id,category_id,group_code=current["GroupCode"],dohyo_number=dohyo_number
                )
            else:
                next_match=db.execute(text("""
                  SELECT TOP (1) m.MatchId FROM dbo.CompetitionMatches m
                  JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
                  WHERE r.EventId=:event AND r.CategoryId=:category AND m.StageCode=:stage
                    AND m.MatchStatus='SCHEDULED'
                        AND NOT EXISTS(SELECT 1 FROM dbo.LiveDohyoMatches l
                          JOIN dbo.CompetitionMatches active ON active.MatchId=l.MatchId
                          JOIN dbo.CompetitionMatchTeams active_team ON active_team.MatchId=active.MatchId
                          JOIN dbo.CompetitionMatchTeams candidate_team ON candidate_team.MatchId=m.MatchId
                            AND candidate_team.TeamId=active_team.TeamId
                          WHERE l.EventId=:event AND l.CategoryId=:category AND active.MatchStatus='LIVE')
                  ORDER BY r.RoundNumber,m.MatchNumber
                """), {"event":event_id,"category":category_id,"stage":current["StageCode"]}).scalar_one_or_none()
            if next_match is None:
                _set_live_dohyo(db,event_id,category_id,dohyo_number,None,user["user_id"])
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
        if payload.match_id:
            match_stage = None if not payload.round_id else db.execute(text("""
              SELECT m.StageCode FROM dbo.CompetitionMatches m
              JOIN dbo.CompetitionMatchTeams mt ON mt.MatchId=m.MatchId
              WHERE m.MatchId=:match AND m.RoundId=:round AND mt.TeamId=:team
            """), {"match": payload.match_id, "round": payload.round_id,
                  "team": payload.team_id}).scalar_one_or_none()
            if match_stage is None:
                raise HTTPException(422, "El enfrentamiento no incluye al equipo indicado.")
            if match_stage != "MANUAL":
                raise HTTPException(409,
                    "Los encuentros del torneo se puntúan con el control de Yukos; no se admite puntuación directa.")
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
            m.PublicDetails AS public_details,m.StageCode AS stage_code,
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
            if match["stage_code"] != "MANUAL":
                raise HTTPException(409,
                    "En encuentros del torneo registra cada Yuko desde el marcador del torneo; no se permite fijar el puntaje directamente.")
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


def _load_live_snapshot(event_id: int, category_id: int | None = None):
    db = SessionLocal()
    try:
        state = db.execute(text("SELECT CompetitionStatus FROM dbo.Events WHERE EventId=:id"),
                           {"id": event_id}).scalar_one_or_none()
        items = _leaderboard(db, event_id, None)
        snapshot = {"event_id": event_id, "status": state,
                    "items": [{k: v for k, v in item.items() if k != "updated_at"} for item in items]}
        if category_id is not None:
            tournament = db.execute(text("""
              SELECT CategoryId FROM dbo.TournamentPhaseState
              WHERE EventId=:event AND CategoryId=:category
            """), {"event": event_id, "category": category_id}).scalar_one_or_none()
        else:
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
async def live_results(websocket: WebSocket, event_id: int, category_id: int | None = None):
    # Public stream exposes standings only, never PII or payment data.
    db = SessionLocal()
    try:
        exists = db.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"), {"id": event_id}).first()
        category_exists = (category_id is None or db.execute(text("""
          SELECT 1 FROM dbo.EventCategories WHERE EventId=:event AND CategoryId=:category
        """), {"event": event_id, "category": category_id}).first())
        if not exists or not category_exists:
            await websocket.close(code=4404)
            return
    finally:
        db.close()
    await websocket.accept()
    last_snapshot = None
    try:
        while True:
            snapshot = await asyncio.to_thread(_load_live_snapshot, event_id, category_id)
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
