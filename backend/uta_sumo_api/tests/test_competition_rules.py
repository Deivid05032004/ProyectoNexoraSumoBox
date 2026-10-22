import asyncio

import pytest
from pydantic import ValidationError

from app.schemas.combat import CurrentCombatUpdate
from app.services.combat_live import LiveCombatConnectionManager
from routers.competition import can_transition, rank_rows


def test_competition_lifecycle_allows_only_documented_transitions():
    assert can_transition("DRAFT", "SCHEDULED")
    assert can_transition("LIVE", "PAUSED")
    assert can_transition("PAUSED", "LIVE")
    assert can_transition("FINISHED", "FINISHED")
    assert not can_transition("FINISHED", "LIVE")
    assert not can_transition("CANCELLED", "SCHEDULED")


def test_leaderboard_preserves_ties_and_ranks_categories_independently():
    rows = [
        {"category_id": 1, "team_id": 4, "points": 10},
        {"category_id": 1, "team_id": 2, "points": 10},
        {"category_id": 1, "team_id": 9, "points": 7},
        {"category_id": 2, "team_id": 3, "points": 7},
    ]
    assert [row["rank"] for row in rank_rows(rows)] == [1, 1, 2, 1]


def test_current_combat_update_accepts_spanish_api_contract_and_requires_pair_scores():
    status = CurrentCombatUpdate.model_validate({"match_id": 12, "estado": "EN_VIVO"})
    assert status.match_id == 12 and status.status == "EN_VIVO"

    score = CurrentCombatUpdate.model_validate({
        "puntaje_a": 2, "puntaje_b": 1, "motivo": "Corrección arbitral",
    })
    assert (score.score_a, score.score_b) == (2, 1)
    assert score.reason == "Corrección arbitral"

    scoreboard_payload = CurrentCombatUpdate.model_validate({
        "id_combate": "COMB-01", "match_id": 12,
        "torneo": "UTA SUMO ROBOTICS CUP 2026", "estado": "En combate",
        "robotA": {"nombre": "Katana II", "institucion": "UTA", "puntos": 2},
        "robotB": {"nombre": "Tornado", "institucion": "La Salle", "puntos": 1},
        "ganador": "No definido", "detalles": "Ronda inicial",
        "motivo": "Marcador confirmado por juez",
    })
    assert scoreboard_payload.status == "EN_VIVO"
    assert (scoreboard_payload.score_a, scoreboard_payload.score_b) == (2, 1)
    assert scoreboard_payload.details == "Ronda inicial"

    details_only = CurrentCombatUpdate.model_validate({"match_id": 12, "detalles": "Reanudado"})
    assert details_only.details == "Reanudado"

    with pytest.raises(ValidationError):
        CurrentCombatUpdate.model_validate({"puntaje_a": 2, "motivo": "Incomplete"})
    with pytest.raises(ValidationError):
        CurrentCombatUpdate.model_validate({"puntaje_a": 2, "puntaje_b": 1})
    with pytest.raises(ValidationError):
        CurrentCombatUpdate.model_validate({"estado": "INVALIDO"})


def test_live_combat_manager_sends_initial_snapshot_and_updates_then_disconnects():
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def accept(self):
            pass

        async def send_json(self, value):
            self.messages.append(value)

    async def exercise():
        manager = LiveCombatConnectionManager()
        socket = FakeWebSocket()
        initial = {"active": False, "estado": "SIN_COMBATE_ACTIVO"}
        await manager.connect(socket, lambda: initial)
        await manager.broadcast({"active": True, "estado": "EN_VIVO"})
        assert socket.messages == [initial, {"active": True, "estado": "EN_VIVO"}]

        await manager.disconnect(socket)
        await manager.broadcast({"active": True, "estado": "FINALIZADO"})
        assert len(socket.messages) == 2

    asyncio.run(exercise())


def test_live_combat_manager_removes_socket_when_broadcast_detects_disconnect():
    from starlette.websockets import WebSocketDisconnect

    class FailingWebSocket:
        def __init__(self):
            self.fail = False

        async def accept(self):
            pass

        async def send_json(self, _value):
            if self.fail:
                raise WebSocketDisconnect()

    async def exercise():
        manager = LiveCombatConnectionManager()
        socket = FailingWebSocket()
        await manager.connect(socket, lambda: {"active": False})
        socket.fail = True
        await manager.broadcast({"active": True})
        assert socket not in manager._connections

    asyncio.run(exercise())
