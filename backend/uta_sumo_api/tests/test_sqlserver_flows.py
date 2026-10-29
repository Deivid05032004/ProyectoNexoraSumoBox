"""Opt-in end-to-end SQL Server tests. All SQL is rolled back per fixture."""
import os
import uuid
from datetime import date
from decimal import Decimal
from time import sleep

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import main
import routers.competition as competition_router
import routers.payments as payments_router
import routers.registrations as registrations_router
import routers.auth as auth_router
import routers.admin as admin_router
import app.services.registration_delivery as registration_delivery
from app.core.security import create_access_token, hash_password
from app.core.crypto import decrypt_text, email_lookup_hash, encrypt_text
from database import engine, get_db


pytestmark = pytest.mark.sqlserver


@pytest.fixture
def sql_api(monkeypatch, tmp_path):
    if os.getenv("RUN_SQLSERVER_TESTS") != "1":
        pytest.skip("Define RUN_SQLSERVER_TESTS=1 para habilitar integración SQL Server.")
    connection = engine.connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    label = uuid.uuid4().hex[:10]
    institution_id = db.execute(text("""
        INSERT INTO dbo.Institutions(Name) OUTPUT INSERTED.InstitutionId
        VALUES (:name)
    """), {"name": f"TEST-{label}"}).scalar_one()
    category_id = db.execute(text("""
        INSERT INTO dbo.Categories(Name,Description) OUTPUT INSERTED.CategoryId
        VALUES (:name,N'isolated test category')
    """), {"name": f"TEST-{label}"}).scalar_one()
    event_id = db.execute(text("""
        INSERT INTO dbo.Events(Name,EditionYear,RegistrationStart,RegistrationEnd,IsActive)
        OUTPUT INSERTED.EventId VALUES (:name,:year,:start,:end,1)
    """), {"name": f"TEST-{label}", "year": date.today().year,
          "start": date(2020,1,1), "end": date(2099,12,31)}).scalar_one()
    db.execute(text("""
        INSERT INTO dbo.Tariffs(EventId,CategoryId,Amount,ValidFrom,ValidUntil,IsActive)
        VALUES (:event,:category,CAST(12.50 AS DECIMAL(10,2)),:start,NULL,1)
    """), {"event": event_id, "category": category_id, "start": date(2020,1,1)})
    db.execute(text("""
        INSERT INTO dbo.EventCategories(EventId,CategoryId,MinParticipants,MaxParticipants,
          MinCoaches,MaxCoaches)
        VALUES (:event,:category,1,30,0,30)
    """), {"event": event_id, "category": category_id})
    db.commit()

    def override_db():
        yield db

    main.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(payments_router, "RECEIPT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(registrations_router, "RECEIPT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(registration_delivery, "RECEIPT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(auth_router, "EMAIL_CHECK_DELIVERABILITY", False)
    monkeypatch.setattr(admin_router, "EMAIL_CHECK_DELIVERABILITY", False)
    # SQL integration tests must never use a developer's configured SMTP
    # account. Individual delivery tests can replace these with a fake server.
    monkeypatch.setattr(registration_delivery, "SMTP_HOST", "")
    monkeypatch.setattr(registration_delivery, "SMTP_FROM_EMAIL", "")
    clients = TestClient(main.app)
    clients.__enter__()
    try:
        yield {"client": clients, "db": db, "institution_id": institution_id,
               "category_id": category_id, "event_id": event_id, "receipt_dir": tmp_path}
    finally:
        clients.__exit__(None, None, None)
        main.app.dependency_overrides.pop(get_db, None)
        db.close()
        outer.rollback()
        connection.close()


def _register(ctx, username):
    email = f"{username}@gmail.com"
    response = ctx["client"].post("/api/v1/auth/register", json={
        "email": email,
        "password": "Robotics-test-password-2026",
        "first_name": "Test",
        "last_name": "Participant",
        "institution_id": ctx["institution_id"],
        "mobile_phone": "0991112222",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _account(ctx, role, username=None):
    username = username or f"test_{role.lower()}_{uuid.uuid4().hex[:8]}@gmail.com"
    role_id = ctx["db"].execute(text("SELECT RoleId FROM dbo.Roles WHERE Code=:role"),
                                 {"role": role}).scalar_one()
    user_id = ctx["db"].execute(text("""
        INSERT INTO dbo.Users(EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive)
        OUTPUT INSERTED.UserId VALUES (:email,:lookup,:hash,:first,:role_name,:role_id,1)
    """), {"email": encrypt_text(username), "lookup": email_lookup_hash(username),
          "hash": hash_password("Robotics-test-password-2026"), "first": encrypt_text("Test"),
          "role_name": role, "role_id": role_id}).scalar_one()
    ctx["db"].commit()
    return {"user_id": user_id, "username": username,
            "headers": {"Authorization": f"Bearer {create_access_token(user_id, role)}"}}


def _owned_resources(ctx, participant_token):
    client = ctx["client"]
    profile = client.get("/api/v1/participants/me", headers=participant_token).json()
    team = client.post("/api/v1/teams", headers=participant_token, json={
        "name": f"Team-{uuid.uuid4().hex[:8]}",
        "institution_id": ctx["institution_id"], "contact_phone": "0990000000",
    })
    assert team.status_code == 201, team.text
    robot = client.post("/api/v1/robots", headers=participant_token, json={
        "name": f"Robot-{uuid.uuid4().hex[:8]}", "team_id": team.json()["id"],
        "robot_description": "test robot",
    })
    assert robot.status_code == 201, robot.text
    return profile, team.json(), robot.json()


def _create_registration(ctx, token):
    profile, team, robot = _owned_resources(ctx, token)
    response = ctx["client"].post("/api/v1/registrations", headers=token, json={
        "event_id": ctx["event_id"], "category_id": ctx["category_id"],
        "team_id": team["id"], "robot_id": robot["id"],
        "participants": [{"participant_id": profile["id"], "role": "PARTICIPANT"}],
        "notes": "isolated test",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_login_owner_isolation_and_duplicate_policy(sql_api):
    ctx = sql_api
    client = ctx["client"]
    assert client.get("/api/v1/registrations").status_code == 401
    first = _register(ctx, f"owner_{uuid.uuid4().hex[:8]}")
    stored = ctx["db"].execute(text("""
        SELECT EmailCiphertext,FirstName,LastName,PasswordHash FROM dbo.Users WHERE UserId=:id
    """), {"id": first["user"]["user_id"]}).one()
    assert stored[0].startswith("enc:v1:") and first["user"]["email"] not in stored[0]
    assert stored[1].startswith("enc:v1:") and stored[2].startswith("enc:v1:")
    assert stored[3].startswith("$argon2id$")
    login = client.post("/api/v1/auth/login", json={
        "email": first["user"]["email"], "password": "Robotics-test-password-2026"})
    assert login.status_code == 200
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=token).json()["role"] == "PARTICIPANT"
    bad_login = client.post("/api/v1/auth/login", json={
        "email": first["user"]["email"], "password": "incorrect-password"})
    assert bad_login.status_code == 401
    changed = client.post("/api/v1/auth/change-password", headers=token, json={
        "current_password": "Robotics-test-password-2026",
        "new_password": "Robotics-new-password-2026",
    })
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me", headers=token).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": first["user"]["email"], "password": "Robotics-test-password-2026"}).status_code == 401
    renewed_login = client.post("/api/v1/auth/login", json={
        "email": first["user"]["email"], "password": "Robotics-new-password-2026"})
    assert renewed_login.status_code == 200
    token = {"Authorization": f"Bearer {renewed_login.json()['access_token']}"}
    profile = client.put("/api/v1/participants/me", headers=token, json={
        "first_name": "Updated", "last_name": "Participant", "mobile_phone": "0993334444"})
    assert profile.status_code == 200
    assert client.get("/api/v1/auth/me", headers=token).json()["first_name"] == "Updated"
    administrator = _account(ctx, "ADMIN")
    admin_ws_token = administrator["headers"]["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect("/api/v1/payments/ws/admin",
                                 subprotocols=["uta-payment-updates", admin_ws_token]) as socket:
        assert socket.receive_json() == {"type": "connected"}
        registration = _create_registration(ctx, token)
        live_registration = socket.receive_json()
        assert live_registration["type"] == "registration.created"
        assert live_registration["registration_id"] == registration["id"]
        assert live_registration["event_id"] == ctx["event_id"]
        assert live_registration["status"] == "PAYMENT_PENDING"
        assert live_registration["payment_status"] == "PENDING"
        assert live_registration["has_receipt"] is False
    assert registration["status"] == "PAYMENT_PENDING"
    assert Decimal(registration["amount"]) == Decimal("12.50")
    registration_page = client.get("/api/v1/registrations?page=1&limit=1", headers=token)
    payment_page = client.get("/api/v1/payments?page=1&limit=1", headers=token)
    assert registration_page.status_code == payment_page.status_code == 200
    assert registration_page.headers["x-total-count"] == "1"
    assert payment_page.headers["x-page-size"] == "1"
    assert client.get(f"/api/v1/registrations/code/{registration['code']}", headers=token).status_code == 200
    duplicate = client.post("/api/v1/registrations", headers=token, json={
        "event_id": ctx["event_id"], "category_id": ctx["category_id"],
        "team_id": registration["team_id"], "robot_id": registration["robot_id"],
        "participants": [{"participant_id": registration["participants"][0]["id"], "role": "PARTICIPANT"}],
    })
    assert duplicate.status_code == 409
    second = _register(ctx, f"other_{uuid.uuid4().hex[:8]}")
    other_token = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get(f"/api/v1/registrations/{registration['id']}", headers=other_token).status_code == 404
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_admin_must_change_password_before_using_admin_endpoints(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin_email = f"must_change_{uuid.uuid4().hex[:8]}@uta.edu.ec"
    admin = _account(ctx, "ADMIN", admin_email)
    ctx["db"].execute(text("UPDATE dbo.Users SET MustChangePassword=1 WHERE UserId=:id"),
                      {"id": admin["user_id"]})
    ctx["db"].commit()
    login = client.post("/api/v1/auth/login", json={
        "email": admin_email, "password": "Robotics-test-password-2026"})
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    old_token = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/admin/roles", headers=old_token).status_code == 403
    with pytest.raises(WebSocketDisconnect) as forced_socket:
        with client.websocket_connect("/api/v1/payments/ws/admin",
                                      subprotocols=["uta-payment-updates", login.json()["access_token"]]):
            pass
    assert forced_socket.value.code == 4403
    changed = client.post("/api/v1/auth/change-password", headers=old_token, json={
        "current_password": "Robotics-test-password-2026",
        "new_password": "Admin-updated-password-2026!",
    })
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me", headers=old_token).status_code == 401
    relogin = client.post("/api/v1/auth/login", json={
        "email": admin_email, "password": "Admin-updated-password-2026!"})
    assert relogin.status_code == 200
    assert relogin.json()["user"]["must_change_password"] is False
    new_token = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    assert client.get("/api/v1/admin/roles", headers=new_token).status_code == 200


def test_three_member_roster_orders_and_mine_queries_persist_without_adding_owner(sql_api):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"roster_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    own_profile, team, robot = _owned_resources(ctx, token)
    payload = {
        "event_id": ctx["event_id"], "category_id": ctx["category_id"],
        "team_id": team["id"], "robot_id": robot["id"],
        "participants": [
            {"role": "PARTICIPANT", "first_name": "Elena", "last_name": "Primera",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991000001"},
            {"role": "PARTICIPANT", "first_name": "Mateo", "last_name": "Segundo",
             "institution_id": ctx["institution_id"], "mobile_phone": None},
            {"role": "COACH", "first_name": "Sofía", "last_name": "Coach",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991000003"},
        ],
    }

    created = client.post("/api/v1/registrations", headers=token, json=payload)
    assert created.status_code == 201, created.text
    detail = created.json()
    assert "created_by_user_id" not in detail
    assert [person["slot"] for person in detail["participants"]] == [
        "PARTICIPANT_1", "PARTICIPANT_2", "COACH"]
    assert [person["role"] for person in detail["participants"]] == [
        "PARTICIPANT", "PARTICIPANT", "COACH"]
    assert own_profile["id"] not in {person["id"] for person in detail["participants"]}
    assert [person["first_name"] for person in detail["participants"]] == [
        "Elena", "Mateo", "Sofía"]
    persisted_members = ctx["db"].execute(text("""
        SELECT p.UserId, p.FirstName, rp.RegistrationPosition
        FROM dbo.RegistrationParticipants rp
        JOIN dbo.Participants p ON p.ParticipantId=rp.ParticipantId
        WHERE rp.RegistrationId=:id ORDER BY rp.RegistrationPosition
    """), {"id": detail["id"]}).all()
    assert [row[0] for row in persisted_members] == [None, None, None]
    assert [row[2] for row in persisted_members] == [1, 2, 3]
    assert all(row[1].startswith("enc:v1:") for row in persisted_members)

    mine = client.get("/api/v1/registrations/my?page=1&limit=10", headers=token)
    assert mine.status_code == 200 and mine.headers["x-total-count"] == "1"
    assert mine.json()[0]["id"] == detail["id"]
    assert mine.json()[0]["payment_id"] == detail["payment_id"]
    assert mine.json()[0]["amount"] == detail["amount"]
    assert len(mine.json()[0]["participants"]) == 3
    again = client.get("/api/v1/registrations/my", headers=token)
    assert again.json()[0]["id"] == detail["id"]
    orders = client.get("/api/v1/payments/my?page=1&limit=10", headers=token)
    assert orders.status_code == 200 and orders.headers["x-total-count"] == "1"
    assert orders.json()[0]["id"] == detail["payment_id"]
    assert orders.json()[0]["registration_code"] == detail["code"]
    assert orders.json()[0]["can_upload_receipt"] is True
    payment_detail = client.get(f"/api/v1/payments/{detail['payment_id']}", headers=token).json()
    assert payment_detail["amount"] == detail["amount"]
    assert payment_detail["can_upload_receipt"] is True

    other = _register(ctx, f"roster_other_{uuid.uuid4().hex[:8]}")
    other_token = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/api/v1/registrations/my", headers=other_token).json() == []
    assert client.get("/api/v1/payments/my", headers=other_token).json() == []
    assert client.get(f"/api/v1/registrations/{detail['id']}", headers=other_token).status_code == 404
    assert client.get(f"/api/v1/payments/{detail['payment_id']}", headers=other_token).status_code == 404


def test_participant_form_resources_then_registration_two_participants_one_coach(sql_api):
    """Cover the same two-request flow used by the participant form."""
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"form_flow_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    profile = client.get("/api/v1/participants/me", headers=token).json()

    resources = client.post("/api/v1/registration-resources", headers=token, json={
        "team_name": f"Team-{uuid.uuid4().hex[:8]}",
        "robot_name": f"Robot-{uuid.uuid4().hex[:8]}",
        "institution_id": profile["institution_id"],
        "contact_phone": profile["mobile_phone"],
        "robot_description": None,
    })
    assert resources.status_code == 201, resources.text

    registration = client.post("/api/v1/registrations", headers=token, json={
        "event_id": ctx["event_id"],
        "category_id": ctx["category_id"],
        "team_id": resources.json()["team"]["id"],
        "robot_id": resources.json()["robot"]["id"],
        "participants": [
            {"role": "PARTICIPANT", "first_name": "Participante", "last_name": "Uno",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991000001"},
            {"role": "PARTICIPANT", "first_name": "Participante", "last_name": "Dos",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991000002"},
            {"role": "COACH", "first_name": "Coach", "last_name": "Prueba",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991000003"},
        ],
        "custom_answers": {},
        "notes": None,
    })
    assert registration.status_code == 201, registration.text
    assert registration.json()["status"] == "PAYMENT_PENDING"
    assert Decimal(registration.json()["amount"]) == Decimal("12.50")
    assert [item["role"] for item in registration.json()["participants"]] == [
        "PARTICIPANT", "PARTICIPANT", "COACH"]


def test_team_names_are_global_unique_but_robot_names_are_unique_per_team(sql_api):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"resource_names_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    profile = client.get("/api/v1/participants/me", headers=token).json()
    team_name = f"Shared-Team-{uuid.uuid4().hex[:8]}"
    robot_name = f"Shared-Robot-{uuid.uuid4().hex[:8]}"
    payload = {
        "team_name": team_name, "robot_name": robot_name,
        "institution_id": profile["institution_id"],
        "contact_phone": profile["mobile_phone"], "robot_description": None,
    }
    first = client.post("/api/v1/registration-resources", headers=token, json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/registration-resources", headers=token,
                         json={**payload, "team_name": f"Second-{uuid.uuid4().hex[:8]}"})
    assert second.status_code == 201, second.text
    assert first.json()["robot"]["name"] == second.json()["robot"]["name"] == robot_name
    assert first.json()["robot"]["team_id"] != second.json()["robot"]["team_id"]

    wrong_team_registration = client.post("/api/v1/registrations", headers=token, json={
        "event_id": ctx["event_id"], "category_id": ctx["category_id"],
        "team_id": first.json()["team"]["id"], "robot_id": second.json()["robot"]["id"],
        "participants": [{"participant_id": profile["id"], "role": "PARTICIPANT"}],
    })
    assert wrong_team_registration.status_code == 422
    assert "no pertenece al equipo" in wrong_team_registration.json()["detail"]

    duplicate_team = client.post("/api/v1/registration-resources", headers=token, json={
        **payload, "robot_name": f"Other-{uuid.uuid4().hex[:8]}"})
    assert duplicate_team.status_code == 409
    assert duplicate_team.json()["detail"]["field"] == "teamName"

    same_team_robot = client.post("/api/v1/robots", headers=token, json={
        "name": robot_name, "team_id": first.json()["team"]["id"],
        "robot_description": None,
    })
    assert same_team_robot.status_code == 409
    assert same_team_robot.json()["detail"]["field"] == "robotName"


def test_official_2026_event_registration_flow_uses_database_configuration(sql_api):
    """Exercise the participant flow against the real official event/category/tariff rows.

    The SQL fixture wraps the entire test in an outer transaction, so the test
    validates order generation without leaving demo registration data behind.
    """
    ctx = sql_api
    client = ctx["client"]
    event = ctx["db"].execute(text("""SELECT e.EventId AS event_id,ec.CategoryId AS category_id,
        t.Amount AS amount FROM dbo.Events e
        JOIN dbo.EventCategories ec ON ec.EventId=e.EventId AND ec.IsActive=1
        JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId AND c.IsActive=1
        JOIN dbo.Tariffs t ON t.EventId=e.EventId AND t.CategoryId=ec.CategoryId AND t.IsActive=1
          AND t.ValidFrom<=CONVERT(date,GETDATE())
          AND (t.ValidUntil IS NULL OR t.ValidUntil>=CONVERT(date,GETDATE()))
        WHERE e.Name=N'UTA SUMO ROBOTICS CUP 2026' AND e.EditionYear=2026
          AND e.IsActive=1 AND c.Name=N'MINI SUMO AMATEUR RC'
          AND ec.MinParticipants=2 AND ec.MaxParticipants=2 AND ec.MinCoaches=1 AND ec.MaxCoaches=1
          AND (e.RegistrationStart IS NULL OR e.RegistrationStart<=CONVERT(date,GETDATE()))
          AND (e.RegistrationEnd IS NULL OR e.RegistrationEnd>=CONVERT(date,GETDATE()))
        ORDER BY t.ValidFrom DESC,t.TariffId DESC""")).mappings().first()
    assert event is not None, "El evento oficial no tiene una categoría y tarifa disponibles."
    public_config = client.get(f"/api/v1/events/{event['event_id']}/registration-config")
    assert public_config.status_code == 200, public_config.text
    assert public_config.json()["registration_open"] is True
    assert public_config.json()["is_enabled"] is True

    participant = _register(ctx, f"official_flow_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    profile = client.get("/api/v1/participants/me", headers=token).json()
    resources = client.post("/api/v1/registration-resources", headers=token, json={
        "team_name": f"QA-Team-{uuid.uuid4().hex[:8]}",
        "robot_name": f"QA-Robot-{uuid.uuid4().hex[:8]}",
        "institution_id": profile["institution_id"],
        "contact_phone": profile["mobile_phone"],
        "robot_description": None,
    })
    assert resources.status_code == 201, resources.text

    registration = client.post("/api/v1/registrations", headers=token, json={
        "event_id": event["event_id"], "category_id": event["category_id"],
        "team_id": resources.json()["team"]["id"],
        "robot_id": resources.json()["robot"]["id"],
        "participants": [
            {"role": "PARTICIPANT", "first_name": "QA", "last_name": "Participante Uno",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991001001"},
            {"role": "PARTICIPANT", "first_name": "QA", "last_name": "Participante Dos",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991001002"},
            {"role": "COACH", "first_name": "QA", "last_name": "Coach",
             "institution_id": ctx["institution_id"], "mobile_phone": "0991001003"},
        ],
        "custom_answers": {}, "notes": None,
    })
    assert registration.status_code == 201, registration.text
    result = registration.json()
    assert result["status"] == "PAYMENT_PENDING"
    assert Decimal(result["amount"]) == Decimal("15.00")
    assert result["payment_status"] == "PENDING"
    assert result["receipt_url"] == f"/api/v1/registrations/{result['id']}/receipt"
    assert result["email_delivery_status"] == "PENDING"
    assert [item["role"] for item in result["participants"]] == [
        "PARTICIPANT", "PARTICIPANT", "COACH"]
    instruction = client.get(result["receipt_url"], headers=token)
    assert instruction.status_code == 200
    assert instruction.headers["content-type"].startswith("application/pdf")


def test_tournament_groups_manage_only_approved_event_category_registrations(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    first_user = _register(ctx, f"group_first_{uuid.uuid4().hex[:8]}")
    second_user = _register(ctx, f"group_second_{uuid.uuid4().hex[:8]}")
    third_user = _register(ctx, f"group_third_{uuid.uuid4().hex[:8]}")
    first_registration = _create_registration(ctx, {"Authorization": f"Bearer {first_user['access_token']}"})
    second_registration = _create_registration(ctx, {"Authorization": f"Bearer {second_user['access_token']}"})
    third_registration = _create_registration(ctx, {"Authorization": f"Bearer {third_user['access_token']}"})
    approved_status = ctx["db"].execute(text(
        "SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED'"
    )).scalar_one()
    ctx["db"].execute(text("""
      UPDATE dbo.Registrations SET StatusId=:status
      WHERE RegistrationId IN (:first,:second,:third)
    """), {"status": approved_status, "first": first_registration["id"],
          "second": second_registration["id"], "third": third_registration["id"]})
    ctx["db"].commit()

    base = (f"/api/v1/admin/events/{ctx['event_id']}/categories/"
            f"{ctx['category_id']}/tournament-groups")
    assert client.get(base).status_code == 401
    created = client.post(base, headers=admin["headers"], json={
        "name": "Grupo Rojo", "code": "rojo-1", "max_teams": 2,
    })
    assert created.status_code == 201, created.text
    first_group = created.json()
    assert first_group["code"] == "ROJO-1" and first_group["assigned_count"] == 0
    second = client.post(base, headers=admin["headers"], json={
        "name": "Grupo Azul", "code": "AZUL", "max_teams": 1,
    })
    assert second.status_code == 201, second.text
    second_group = second.json()
    edited = client.patch(f"{base}/{first_group['id']}", headers=admin["headers"], json={
        "name": "Grupo Rojo A",
    })
    assert edited.status_code == 200 and edited.json()["name"] == "Grupo Rojo A"

    available = client.get(f"{base}/eligible-registrations?page=1&limit=5", headers=admin["headers"])
    assert available.status_code == 200
    assert {item["registration_id"] for item in available.json()["items"]} == {
        first_registration["id"], second_registration["id"], third_registration["id"]
    }
    invalid = client.post(f"{base}/{first_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": 999999,
    })
    assert invalid.status_code == 422

    assigned = client.post(f"{base}/{first_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": first_registration["id"],
    })
    assert assigned.status_code == 201, assigned.text
    registered_team_id = ctx["db"].execute(text(
        "SELECT TeamId FROM dbo.Registrations WHERE RegistrationId=:id"
    ), {"id": first_registration["id"]}).scalar_one()
    group_view = client.get(f"{base}/{first_group['id']}/participants", headers=admin["headers"])
    assert group_view.status_code == 200
    assert group_view.json()["teams"][0]["team_id"] == registered_team_id
    assert len(group_view.json()["participants"]) == 1
    assert group_view.json()["participants"][0]["role"] == "PARTICIPANT"

    second_assigned = client.post(f"{base}/{first_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": second_registration["id"],
    })
    assert second_assigned.status_code == 201, second_assigned.text
    capacity_conflict = client.patch(f"{base}/{first_group['id']}", headers=admin["headers"], json={
        "max_teams": 1,
    })
    assert capacity_conflict.status_code == 409

    full = client.post(f"{base}/{first_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": third_registration["id"],
    })
    assert full.status_code == 409
    full = client.post(f"{base}/{first_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": first_registration["id"],
    })
    assert full.status_code == 409  # An assignment cannot be duplicated in one group.
    duplicate = client.post(f"{base}/{second_group['id']}/registrations", headers=admin["headers"], json={
        "registration_id": first_registration["id"],
    })
    assert duplicate.status_code == 409
    too_small = client.patch(f"{base}/{first_group['id']}", headers=admin["headers"], json={
        "max_teams": 0,
    })
    assert too_small.status_code == 422

    moved = client.put(
        f"{base}/{second_group['id']}/registrations/{first_registration['id']}",
        headers=admin["headers"],
    )
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"moved": True, "registration_id": first_registration["id"],
                            "from_group_id": first_group["id"], "to_group_id": second_group["id"]}
    assert client.get(f"{base}/{second_group['id']}/participants", headers=admin["headers"]).json()["teams"][0]["registration_id"] == first_registration["id"]
    removed = client.delete(
        f"{base}/{second_group['id']}/registrations/{first_registration['id']}",
        headers=admin["headers"],
    )
    assert removed.status_code == 204
    deleted = client.delete(f"{base}/{second_group['id']}", headers=admin["headers"])
    assert deleted.status_code == 204

    # A configured GROUP phase is still editable before the start command. Once
    # the state advances, all assignment and structure mutations are rejected.
    ctx["db"].execute(text("""
      INSERT dbo.TournamentPhaseState(EventId,CategoryId,CurrentPhase,CreatedByUserId,UpdatedByUserId)
      VALUES(:event,:category,'SEMIFINAL',:actor,:actor)
    """), {"event": ctx["event_id"], "category": ctx["category_id"], "actor": admin["user_id"]})
    ctx["db"].commit()
    locked = client.get(base, headers=admin["headers"])
    assert locked.status_code == 200 and locked.json()["locked"] is True
    no_edit = client.patch(f"{base}/{first_group['id']}", headers=admin["headers"], json={"name": "Otro"})
    assert no_edit.status_code == 409
    no_delete = client.delete(f"{base}/{first_group['id']}", headers=admin["headers"])
    assert no_delete.status_code == 409


def test_tournament_calendar_uses_saved_group_assignments(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    group_base = (f"/api/v1/admin/events/{ctx['event_id']}/categories/"
                  f"{ctx['category_id']}/tournament-groups")
    groups = {}
    for code in "ABCD":
        response = client.post(group_base, headers=admin["headers"], json={
            "name": f"Grupo {code}", "code": code, "max_teams": 2,
        })
        assert response.status_code == 201, response.text
        groups[code] = response.json()["id"]

    registrations = []
    for index in range(8):
        participant = _register(ctx, f"bracket_{uuid.uuid4().hex[:10]}")
        registration = _create_registration(ctx, {
            "Authorization": f"Bearer {participant['access_token']}"})
        registrations.append(registration["id"])
    approved_status = ctx["db"].execute(text(
        "SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED'"
    )).scalar_one()
    ctx["db"].execute(text("UPDATE dbo.Registrations SET StatusId=:status WHERE RegistrationId IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"status": approved_status, "ids": registrations})
    ctx["db"].commit()

    for index, registration_id in enumerate(registrations):
        code = "ABCD"[index // 2]
        assigned = client.post(f"{group_base}/{groups[code]}/registrations",
            headers=admin["headers"], json={"registration_id": registration_id})
        assert assigned.status_code == 201, assigned.text

    built = client.post(f"/api/v1/events/{ctx['event_id']}/tournament/from-groups",
        headers=admin["headers"], json={"category_id": ctx["category_id"]})
    assert built.status_code == 200, built.text
    tournament = built.json()
    assert tournament["phase"] == "GROUP"
    assert {code: len(rows) for code, rows in tournament["groups"].items()} == {
        "A": 2, "B": 2, "C": 2, "D": 2,
    }
    group_matches = [match for match in tournament["matches"] if match["stage_code"] == "GROUP"]
    assert len(group_matches) == 4
    assert {match["group_code"] for match in group_matches} == set("ABCD")
    assert all(match["status"] == "SCHEDULED" and match["group_name"] for match in group_matches)
    relation_count = ctx["db"].execute(text("""
      SELECT COUNT(*) FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds r ON r.RoundId=m.RoundId
      WHERE m.TournamentGroupId IS NOT NULL AND m.StageCode='GROUP'
        AND r.EventId=:event AND r.CategoryId=:category
    """), {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one()
    assert relation_count == 4

    def finish_stage(stage):
        ctx["db"].execute(text("""
          UPDATE m SET MatchStatus='FINISHED',WinnerTeamId=left_team.TeamId,LoserTeamId=right_team.TeamId
          FROM dbo.CompetitionMatches m
          JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
          JOIN dbo.CompetitionMatchTeams left_team ON left_team.MatchId=m.MatchId AND left_team.TeamPosition=1
          JOIN dbo.CompetitionMatchTeams right_team ON right_team.MatchId=m.MatchId AND right_team.TeamPosition=2
          WHERE cr.EventId=:event AND cr.CategoryId=:category AND m.StageCode=:stage
        """), {"event": ctx["event_id"], "category": ctx["category_id"], "stage": stage})
        ctx["db"].commit()
        competition_router._advance_tournament_phase(
            ctx["db"], ctx["event_id"], ctx["category_id"], admin["user_id"])
        ctx["db"].commit()

    finish_stage("GROUP")
    after_groups = client.get(
        f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"],
    ).json()
    assert after_groups["phase"] == "QUARTERFINAL"
    assert sum(board["match"] is not None for board in after_groups["boards"]) == 4
    finish_stage("QUARTERFINAL")
    after_quarters = client.get(
        f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"],
    ).json()
    assert after_quarters["phase"] == "SEMIFINAL"
    assert sum(board["match"] is not None for board in after_quarters["boards"]) == 2
    finish_stage("SEMIFINAL")
    assert ctx["db"].execute(text("""SELECT CurrentPhase FROM dbo.TournamentPhaseState
      WHERE EventId=:event AND CategoryId=:category"""),
      {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one() == "THIRD_PLACE"
    finish_stage("THIRD_PLACE")
    final = ctx["db"].execute(text("""SELECT m.ScoreToWin FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      WHERE cr.EventId=:event AND cr.CategoryId=:category AND m.StageCode='FINAL'"""),
      {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one()
    assert final == 3
    assert ctx["db"].execute(text("""
      SELECT COUNT(*) FROM dbo.CompetitionMatches m
      JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
      WHERE cr.EventId=:event AND cr.CategoryId=:category
        AND ((m.StageCode='FINAL' AND m.ScoreToWin<>3)
          OR (m.StageCode<>'MANUAL' AND m.StageCode<>'FINAL' AND m.ScoreToWin<>2))
    """), {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one() == 0
    finish_stage("FINAL")
    assert ctx["db"].execute(text("""SELECT CurrentPhase FROM dbo.TournamentPhaseState
      WHERE EventId=:event AND CategoryId=:category"""),
      {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one() == "FINISHED"


def test_custom_groups_and_non_power_of_two_bracket_progress(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    group_base = (f"/api/v1/admin/events/{ctx['event_id']}/categories/"
                  f"{ctx['category_id']}/tournament-groups")
    group_ids = {}
    for code in ("NORTE", "SUR", "ESTE"):
        created = client.post(group_base, headers=admin["headers"], json={
            "name": f"Zona {code}", "code": code, "max_teams": 2,
        })
        assert created.status_code == 201, created.text
        group_ids[code] = created.json()["id"]

    registrations = []
    for index in range(6):
        participant = _register(ctx, f"flexbracket_{uuid.uuid4().hex[:10]}")
        registrations.append(_create_registration(ctx, {
            "Authorization": f"Bearer {participant['access_token']}"})["id"])
    approved_status = ctx["db"].execute(text(
        "SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED'"
    )).scalar_one()
    ctx["db"].execute(text("UPDATE dbo.Registrations SET StatusId=:status WHERE RegistrationId IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"status": approved_status, "ids": registrations})
    ctx["db"].commit()

    for index, registration_id in enumerate(registrations):
        code = ("NORTE", "SUR", "ESTE")[index // 2]
        assigned = client.post(f"{group_base}/{group_ids[code]}/registrations",
            headers=admin["headers"], json={"registration_id": registration_id})
        assert assigned.status_code == 201, assigned.text

    built = client.post(f"/api/v1/events/{ctx['event_id']}/tournament/from-groups",
        headers=admin["headers"], json={"category_id": ctx["category_id"]})
    assert built.status_code == 200, built.text
    group_matches = [m for m in built.json()["matches"] if m["stage_code"] == "GROUP"]
    assert len(group_matches) == 3  # One unique pair in each two-team group.
    assert {m["group_code"] for m in group_matches} == {"NORTE", "SUR", "ESTE"}
    pairs = [(m["group_code"], frozenset((m["team_id_a"], m["team_id_b"]))) for m in group_matches]
    assert len(pairs) == len(set(pairs))

    def finish_stage(stage):
        ctx["db"].execute(text("""
          UPDATE m SET MatchStatus='FINISHED',WinnerTeamId=left_team.TeamId,LoserTeamId=right_team.TeamId
          FROM dbo.CompetitionMatches m
          JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
          JOIN dbo.CompetitionMatchTeams left_team ON left_team.MatchId=m.MatchId AND left_team.TeamPosition=1
          JOIN dbo.CompetitionMatchTeams right_team ON right_team.MatchId=m.MatchId AND right_team.TeamPosition=2
          WHERE cr.EventId=:event AND cr.CategoryId=:category AND m.StageCode=:stage
        """), {"event": ctx["event_id"], "category": ctx["category_id"], "stage": stage})
        ctx["db"].commit()
        competition_router._advance_tournament_phase(
            ctx["db"], ctx["event_id"], ctx["category_id"], admin["user_id"])
        ctx["db"].commit()

    finish_stage("GROUP")
    quarterfinals = client.get(f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"]).json()
    assert quarterfinals["phase"] == "QUARTERFINAL"
    assert sum(board["match"] is not None for board in quarterfinals["boards"]) == 2
    bye_count = ctx["db"].execute(text("""SELECT COUNT(*) FROM dbo.TournamentBracketByes
      WHERE EventId=:event AND CategoryId=:category AND StageCode='QUARTERFINAL'"""),
      {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one()
    assert bye_count == 2
    finish_stage("QUARTERFINAL")
    semifinal = client.get(f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"]).json()
    assert semifinal["phase"] == "SEMIFINAL"
    assert sum(board["match"] is not None for board in semifinal["boards"]) == 2


def test_two_groups_progress_to_semifinals_then_third_place_and_one_final(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    group_base = (f"/api/v1/admin/events/{ctx['event_id']}/categories/"
                  f"{ctx['category_id']}/tournament-groups")
    groups = {}
    for code in ("A", "B"):
        response = client.post(group_base, headers=admin["headers"], json={
            "name": f"Grupo {code}", "code": code, "max_teams": 2,
        })
        assert response.status_code == 201, response.text
        groups[code] = response.json()["id"]
    registration_ids = []
    for index in range(4):
        participant = _register(ctx, f"two_groups_{uuid.uuid4().hex[:10]}")
        registration_ids.append(_create_registration(ctx, {
            "Authorization": f"Bearer {participant['access_token']}"})["id"])
    approved = ctx["db"].execute(text(
        "SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED'"
    )).scalar_one()
    ctx["db"].execute(text("UPDATE dbo.Registrations SET StatusId=:status WHERE RegistrationId IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"status": approved, "ids": registration_ids})
    ctx["db"].commit()
    for index, registration_id in enumerate(registration_ids):
        code = "A" if index < 2 else "B"
        assigned = client.post(f"{group_base}/{groups[code]}/registrations",
            headers=admin["headers"], json={"registration_id": registration_id})
        assert assigned.status_code == 201, assigned.text

    created = client.post(f"/api/v1/events/{ctx['event_id']}/tournament/from-groups",
        headers=admin["headers"], json={"category_id": ctx["category_id"]})
    assert created.status_code == 200, created.text
    assert created.json()["phase_progress"] == {
        "stage": "GROUP", "total": 2, "finished": 0, "live": 0,
        "scheduled": 2, "cancelled": 0, "remaining": 2, "complete": False,
    }
    with pytest.raises(HTTPException) as blocked:
        competition_router._advance_tournament_phase(
            ctx["db"], ctx["event_id"], ctx["category_id"], admin["user_id"])
    assert blocked.value.status_code == 409
    ctx["db"].commit()

    def finish(stage):
        ctx["db"].execute(text("""
          UPDATE m SET MatchStatus='FINISHED',WinnerTeamId=left_team.TeamId,LoserTeamId=right_team.TeamId
          FROM dbo.CompetitionMatches m
          JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
          JOIN dbo.CompetitionMatchTeams left_team ON left_team.MatchId=m.MatchId AND left_team.TeamPosition=1
          JOIN dbo.CompetitionMatchTeams right_team ON right_team.MatchId=m.MatchId AND right_team.TeamPosition=2
          WHERE cr.EventId=:event AND cr.CategoryId=:category AND m.StageCode=:stage
        """), {"event": ctx["event_id"], "category": ctx["category_id"], "stage": stage})
        ctx["db"].commit()
        competition_router._advance_tournament_phase(
            ctx["db"], ctx["event_id"], ctx["category_id"], admin["user_id"])
        ctx["db"].commit()

    finish("GROUP")
    with pytest.raises(HTTPException) as duplicate_advance:
        competition_router._advance_tournament_phase(
            ctx["db"], ctx["event_id"], ctx["category_id"], admin["user_id"])
    assert duplicate_advance.value.status_code == 409
    ctx["db"].commit()
    semifinal = client.get(f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"]).json()
    assert semifinal["phase"] == "SEMIFINAL"
    assert {match["stage_code"] for match in semifinal["matches"]} == {"GROUP", "SEMIFINAL"}

    finish("SEMIFINAL")
    assert ctx["db"].execute(text("""SELECT CurrentPhase FROM dbo.TournamentPhaseState
      WHERE EventId=:event AND CategoryId=:category"""),
      {"event": ctx["event_id"], "category": ctx["category_id"]}).scalar_one() == "THIRD_PLACE"
    finish("THIRD_PLACE")
    final = client.get(f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"]).json()
    assert final["phase"] == "FINAL"
    assert sum(match["stage_code"] == "FINAL" for match in final["matches"]) == 1
    finish("FINAL")
    completed = client.get(f"/api/v1/events/{ctx['event_id']}/tournament?category_id={ctx['category_id']}",
        headers=admin["headers"]).json()
    assert completed["phase"] == "FINISHED"
    assert completed["phase_progress"]["complete"] is True


def test_staff_can_select_group_matches_without_crossing_groups_or_journeys(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    group_base = (f"/api/v1/admin/events/{ctx['event_id']}/categories/"
                  f"{ctx['category_id']}/tournament-groups")
    group_ids = {}
    for code in ("A", "B"):
        created = client.post(group_base, headers=admin["headers"], json={
            "name": f"Grupo {code}", "code": code, "max_teams": 3,
        })
        assert created.status_code == 201, created.text
        group_ids[code] = created.json()["id"]
    registrations = []
    for index in range(6):
        participant = _register(ctx, f"pickfight_{uuid.uuid4().hex[:10]}")
        registrations.append(_create_registration(ctx, {
            "Authorization": f"Bearer {participant['access_token']}"})["id"])
    approved_status = ctx["db"].execute(text(
        "SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED'"
    )).scalar_one()
    ctx["db"].execute(text("UPDATE dbo.Registrations SET StatusId=:status WHERE RegistrationId IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"status": approved_status, "ids": registrations})
    ctx["db"].commit()
    for index, registration_id in enumerate(registrations):
        code = "A" if index < 3 else "B"
        assigned = client.post(f"{group_base}/{group_ids[code]}/registrations",
            headers=admin["headers"], json={"registration_id": registration_id})
        assert assigned.status_code == 201, assigned.text

    built = client.post(f"/api/v1/events/{ctx['event_id']}/tournament/from-groups",
        headers=admin["headers"], json={"category_id": ctx["category_id"]})
    assert built.status_code == 200, built.text
    matches = [match for match in built.json()["matches"] if match["stage_code"] == "GROUP"]
    first_round = [match for match in matches if match["schedule_round"] == 1]
    assert {match["group_code"] for match in first_round} == {"A", "B"}

    start_path = f"/api/v1/events/{ctx['event_id']}/tournament/matches"
    group_a_first = next(match for match in first_round if match["group_code"] == "A")
    group_b_first = next(match for match in first_round if match["group_code"] == "B")
    assert {match["dohyo_number"] for match in matches if match["group_code"] == "A"} == {1}
    assert {match["dohyo_number"] for match in matches if match["group_code"] == "B"} == {2}
    first = client.post(f"{start_path}/{group_a_first['match_id']}/start?category_id={ctx['category_id']}&dohyo_number=1",
        headers=admin["headers"])
    second = client.post(f"{start_path}/{group_b_first['match_id']}/start?category_id={ctx['category_id']}&dohyo_number=2",
        headers=admin["headers"])
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert {board["match"]["group_code"] for board in second.json()["boards"] if board["match"]} == {"A", "B"}

    later_match = next(match for match in matches if match["group_code"] == group_a_first["group_code"]
                       and match["schedule_round"] == 2)
    blocked = client.post(f"{start_path}/{later_match['match_id']}/start?category_id={ctx['category_id']}&dohyo_number=3",
        headers=admin["headers"])
    assert blocked.status_code == 409

    ctx["db"].execute(text("""
      UPDATE dbo.CompetitionMatches SET MatchStatus='FINISHED',WinnerTeamId=:winner,LoserTeamId=:loser
      WHERE MatchId=:match
    """), {"winner": group_a_first["team_id_a"], "loser": group_a_first["team_id_b"],
          "match": group_a_first["match_id"]})
    ctx["db"].commit()
    assert client.post(
        f"{start_path}/{later_match['match_id']}/start?category_id={ctx['category_id']}&dohyo_number=3",
        headers=admin["headers"],
    ).status_code == 409
    next_a = client.post(
        f"{start_path}/{later_match['match_id']}/start?category_id={ctx['category_id']}&dohyo_number=1",
        headers=admin["headers"],
    )
    assert next_a.status_code == 200, next_a.text
    group_a_board = next(board for board in next_a.json()["boards"] if board["dohyo_number"] == 1)
    assert group_a_board["match"]["group_code"] == "A"
    assert group_a_board["match"]["match_id"] == later_match["match_id"]


def test_event_category_roster_rules_are_configurable_and_enforced(sql_api):
    ctx = sql_api
    admin = _account(ctx, "ADMIN")
    rules = {
        "is_active": True, "min_participants": 2, "max_participants": 3,
        "min_coaches": 1, "max_coaches": 1, "max_registrations": 10,
    }
    configured = ctx["client"].put(
        f"/api/v1/admin/events/{ctx['event_id']}/categories/{ctx['category_id']}",
        headers=admin["headers"], json=rules,
    )
    assert configured.status_code == 200, configured.text
    public = ctx["client"].get(f"/api/v1/events/{ctx['event_id']}/categories")
    assert public.status_code == 200
    assert public.json()[0]["min_participants"] == 2
    assert public.json()[0]["max_registrations"] == 10

    participant = _register(ctx, f"configured_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    _profile, team, robot = _owned_resources(ctx, token)
    one_member = ctx["client"].post("/api/v1/registrations", headers=token, json={
        "event_id": ctx["event_id"], "category_id": ctx["category_id"],
        "team_id": team["id"], "robot_id": robot["id"],
        "participants": [{"role": "PARTICIPANT", "first_name": "Only",
            "last_name": "Member", "institution_id": ctx["institution_id"],
            "mobile_phone": None}],
    })
    assert one_member.status_code == 422


def test_admin_creates_custom_category_and_attaches_it_atomically(sql_api):
    ctx = sql_api
    admin = _account(ctx, "ADMIN")
    participant = _register(ctx, f"categoryuser_{uuid.uuid4().hex[:8]}")
    payload = {
        "name": f"Sumo personalizado {uuid.uuid4().hex[:6]}",
        "description": "  Categoría creada desde administración  ",
        "is_active": True, "min_participants": 1, "max_participants": 2,
        "min_coaches": 0, "max_coaches": 1,
    }
    forbidden = ctx["client"].post(
        f"/api/v1/admin/events/{ctx['event_id']}/categories",
        headers={"Authorization": f"Bearer {participant['access_token']}"}, json=payload,
    )
    assert forbidden.status_code == 403
    created = ctx["client"].post(
        f"/api/v1/admin/events/{ctx['event_id']}/categories",
        headers=admin["headers"], json=payload,
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["name"] == payload["name"]
    assert result["description"] == "Categoría creada desde administración"
    assert result["event_id"] == ctx["event_id"]
    assert result["is_active"] is True
    stored = ctx["db"].execute(text("""
        SELECT COUNT_BIG(*) FROM dbo.Categories c
        JOIN dbo.EventCategories ec ON ec.CategoryId=c.CategoryId
        WHERE c.CategoryId=:category AND ec.EventId=:event
    """), {"category": result["id"], "event": ctx["event_id"]}).scalar_one()
    assert stored == 1
    duplicate = ctx["client"].post(
        f"/api/v1/admin/events/{ctx['event_id']}/categories",
        headers=admin["headers"], json=payload,
    )
    assert duplicate.status_code == 409




def test_catalog_admin_permissions_and_role_management(sql_api):
    ctx = sql_api
    admin = _account(ctx, "ADMIN")
    participant = _register(ctx, f"normal_{uuid.uuid4().hex[:8]}")
    participant_token = {"Authorization": f"Bearer {participant['access_token']}"}
    profile, team, _ = _owned_resources(ctx, participant_token)
    event_manager = _account(ctx, "EVENT_MANAGER")
    operational_event = ctx["client"].post("/api/v1/events", headers=event_manager["headers"], json={
        "name": f"OPERATIONS-{uuid.uuid4().hex[:8]}", "edition_year": date.today().year,
        "registration_start": "2020-01-01", "registration_end": "2020-01-02", "is_active": True,
    })
    assert operational_event.status_code == 201, operational_event.text
    catalog_page = ctx["client"].get("/api/v1/events?page=1&limit=1")
    assert catalog_page.status_code == 200 and len(catalog_page.json()) <= 1
    assert catalog_page.headers["x-page"] == "1"
    assert int(catalog_page.headers["x-total-count"]) >= len(catalog_page.json())
    category_page = ctx["client"].get("/api/v1/categories?page=1&limit=1")
    assert category_page.status_code == 200 and len(category_page.json()) <= 1
    assert category_page.headers["x-page-size"] == "1"
    institution_page = ctx["client"].get("/api/v1/institutions?page=1&limit=1")
    tariff_page = ctx["client"].get(
        f"/api/v1/tariffs?event_id={ctx['event_id']}&category_id={ctx['category_id']}&page=1&limit=1"
    )
    assert institution_page.status_code == tariff_page.status_code == 200
    assert len(institution_page.json()) <= 1 and len(tariff_page.json()) == 1
    assert tariff_page.headers["x-total-pages"] == "1"
    event_manager_teams_response = ctx["client"].get("/api/v1/teams?page=1&limit=1", headers=event_manager["headers"])
    event_manager_teams = event_manager_teams_response.json()
    assert event_manager_teams_response.headers["x-page-size"] == "1"
    assert next(item for item in event_manager_teams if item["id"] == team["id"])["contact_phone"] is None
    event_manager_participants_response = ctx["client"].get("/api/v1/participants?page=1&limit=1", headers=event_manager["headers"])
    event_manager_participants = event_manager_participants_response.json()
    assert event_manager_participants_response.headers["x-page"] == "1"
    assert next(item for item in event_manager_participants if item["id"] == profile["id"])["mobile_phone"] is None
    admin_participants = ctx["client"].get("/api/v1/participants", headers=admin["headers"]).json()
    assert next(item for item in admin_participants if item["id"] == profile["id"])["mobile_phone"] == "0991112222"
    admin_page = ctx["client"].get("/api/v1/admin/users?page=1&limit=1", headers=admin["headers"])
    audit_page = ctx["client"].get("/api/v1/admin/audit/users?page=1&limit=1", headers=admin["headers"])
    assert admin_page.status_code == audit_page.status_code == 200
    assert len(admin_page.json()) <= 1 and admin_page.headers["x-page"] == "1"
    assert len(audit_page.json()) <= 1 and audit_page.headers["x-page-size"] == "1"
    forbidden = ctx["client"].post("/api/v1/categories", headers=participant_token,
                                   json={"name": "forbidden", "description": None})
    assert forbidden.status_code == 403
    created = ctx["client"].post("/api/v1/categories", headers=admin["headers"],
                                  json={"name": f"ADMIN-{uuid.uuid4().hex[:8]}", "description": "test"})
    assert created.status_code == 201, created.text
    event = ctx["client"].post("/api/v1/events", headers=admin["headers"], json={
        "name": f"ADMIN-{uuid.uuid4().hex[:8]}", "edition_year": date.today().year,
        "registration_start": "2020-01-01", "registration_end": "2020-01-02", "is_active": True,
    })
    assert event.status_code == 201
    bad_tariff = ctx["client"].post("/api/v1/tariffs", headers=admin["headers"], json={
        "event_id": event.json()["id"], "category_id": 999999,
        "amount": "1.00", "valid_from": "2020-01-01", "is_active": True,
    })
    assert bad_tariff.status_code == 422
    assert ctx["client"].get("/api/v1/admin/users", headers=participant_token).status_code == 403
    assert {role["code"] for role in ctx["client"].get("/api/v1/admin/roles", headers=admin["headers"]).json()} == {
        "ADMIN", "EVENT_MANAGER", "PARTICIPANT"
    }
    updated_role = ctx["client"].patch(f"/api/v1/admin/users/{participant['user']['user_id']}",
                                        headers=admin["headers"], json={"role": "EVENT_MANAGER"})
    assert updated_role.status_code == 200 and updated_role.json()["role"] == "EVENT_MANAGER"
    audit = ctx["client"].get("/api/v1/admin/audit/users?target_user_id=" +
                              str(participant["user"]["user_id"]), headers=admin["headers"])
    assert audit.status_code == 200 and audit.json()[0]["action"] == "ACCOUNT_UPDATED"
    assert ctx["client"].get("/api/v1/admin/audit/users",
                            headers={"Authorization": f"Bearer {participant['access_token']}"}).status_code == 401
    # Local demo bootstrap leaves a real ADMIN; remove it inside this rollback-only
    # test transaction so the self-demotion assertion exercises the last-admin case.
    ctx["db"].execute(text("""
        UPDATE dbo.Users SET IsActive=0 WHERE RoleId=(SELECT RoleId FROM dbo.Roles WHERE Code='ADMIN')
          AND UserId<>:test_admin
    """), {"test_admin": admin["user_id"]})
    ctx["db"].commit()
    assert ctx["client"].patch(f"/api/v1/admin/users/{admin['user_id']}",
                                headers=admin["headers"], json={"is_active": False}).status_code == 409


def test_payment_receipt_review_history_and_state_transitions(sql_api, monkeypatch):
    ctx = sql_api
    client = ctx["client"]
    # Keep integration tests isolated from external SMTP while validating the
    # durable outbox entry created by receipt submission.
    monkeypatch.setattr(payments_router, "deliver_outbox", lambda _db, _id: "PENDING")
    participant = _register(ctx, f"payer_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    registration = _create_registration(ctx, token)
    payment_id = registration["payment_id"]
    second = _register(ctx, f"nonowner_{uuid.uuid4().hex[:8]}")
    nonowner = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get(f"/api/v1/payments/{payment_id}/receipt", headers=nonowner).status_code == 404
    bad = client.post(f"/api/v1/payments/{payment_id}/receipt", headers=token,
                      files={"file": ("proof.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 415
    too_large = client.post(f"/api/v1/payments/{payment_id}/receipt", headers=token,
                            files={"file": ("large.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024), "application/pdf")})
    assert too_large.status_code == 413
    administrator = _account(ctx, "ADMIN")
    event_manager = _account(ctx, "EVENT_MANAGER")
    assert client.get("/api/v1/payments/my", headers=event_manager["headers"]).status_code == 403
    assert client.get("/api/v1/registrations/my", headers=event_manager["headers"]).status_code == 403
    assert client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                       json={"status": "REJECTED"}).status_code == 409
    assert client.post(f"/api/v1/registrations/{registration['id']}/review",
                       headers=event_manager["headers"],
                       json={"status": "APPROVED"}).status_code == 403
    with pytest.raises(WebSocketDisconnect) as forbidden_socket:
        with client.websocket_connect("/api/v1/payments/ws/admin",
                                      subprotocols=["uta-payment-updates", participant["access_token"]]):
            pass
    assert forbidden_socket.value.code == 4403
    ws_admin = ctx["db"].execute(text("""
        SELECT TOP (1) u.UserId,u.TokenVersion FROM dbo.Users u
        JOIN dbo.Roles r ON r.RoleId=u.RoleId WHERE r.Code='ADMIN' AND u.IsActive=1
        ORDER BY u.UserId
    """)).one()
    admin_ws_token = create_access_token(ws_admin[0], "ADMIN", ws_admin[1])
    with client.websocket_connect("/api/v1/payments/ws/admin",
                                  subprotocols=["uta-payment-updates", admin_ws_token]) as socket:
        assert socket.accepted_subprotocol == "uta-payment-updates"
        assert socket.receive_json() == {"type": "connected"}
        submitted = client.post(f"/api/v1/payments/{payment_id}/receipt", headers=token,
                                data={"payment_reference": "bank-transfer-test"},
                                files={"file": ("proof.pdf", b"%PDF-1.7\nmock evidence", "application/pdf")})
        assert submitted.status_code == 202, submitted.text
        live_update = socket.receive_json()
        assert live_update["type"] == "payment.receipt_submitted"
        assert live_update["payment_id"] == payment_id
        assert live_update["registration_id"] == registration["id"]
        assert live_update["status"] == "IN_REVIEW"
        assert live_update["has_receipt"] is True
        assert "receipt_key" not in live_update
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["notification_status"] == "PENDING"
    proof_email = ctx["db"].execute(text("""
        SELECT MessageType,RecipientCiphertext,Subject,BodyText FROM dbo.EmailOutbox
        WHERE RegistrationId=:id AND MessageType LIKE 'PAYMENT_PROOF_%'
    """), {"id": registration["id"]}).one()
    assert proof_email[0].startswith("PAYMENT_PROOF_")
    assert all(value.startswith("enc:v1:") for value in proof_email[1:])
    assert "Recibimos el comprobante" in decrypt_text(proof_email[3])
    stored_receipt = ctx["db"].execute(text("""
        SELECT pr.EncryptionVersion,pr.StorageKey,p.PaymentReference
        FROM dbo.PaymentReceipts pr JOIN dbo.Payments p ON p.PaymentId=pr.PaymentId
        WHERE pr.PaymentId=:id AND pr.IsCurrent=1
    """), {"id": payment_id}).one()
    assert stored_receipt[0] == 1
    assert (ctx["receipt_dir"] / stored_receipt[1]).read_bytes().startswith(b"UTAENC1")
    assert stored_receipt[2].startswith("enc:v1:")
    assert submitted.json()["status"] == "IN_REVIEW"
    in_review_orders = client.get("/api/v1/payments/my", headers=token)
    assert in_review_orders.status_code == 200
    assert in_review_orders.json()[0]["status"] == "IN_REVIEW"
    assert in_review_orders.json()[0]["has_receipt"] is True
    assert in_review_orders.json()[0]["can_upload_receipt"] is False
    assert client.get(f"/api/v1/payments/{payment_id}", headers=token).json()["can_upload_receipt"] is False
    download = client.get(f"/api/v1/payments/{payment_id}/receipt", headers=token)
    assert download.status_code == 200 and download.content.startswith(b"%PDF-")
    missing_reason = client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                                 json={"status": "REJECTED"})
    assert missing_reason.status_code == 422
    with client.websocket_connect("/api/v1/payments/ws/admin",
                                 subprotocols=["uta-payment-updates", admin_ws_token]) as socket:
        assert socket.receive_json() == {"type": "connected"}
        rejected = client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                               json={"status": "REJECTED", "comments": "evidencia ilegible"})
        live_review = socket.receive_json()
        assert live_review["type"] == "payment.reviewed"
        assert live_review["payment_id"] == payment_id
        assert live_review["status"] == "REJECTED"
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert rejected.json()["notification_status"] == "PENDING"
    rejected_order = client.get("/api/v1/payments/my", headers=token).json()[0]
    assert rejected_order["can_upload_receipt"] is True
    assert rejected_order["review_comments"] == "evidencia ilegible"
    rejected_email = ctx["db"].execute(text("""
        SELECT RecipientCiphertext,Subject,BodyText FROM dbo.EmailOutbox
        WHERE RegistrationId=:id AND MessageType LIKE 'PAYMENT_REJECTED_%'
    """), {"id": registration["id"]}).one()
    assert all(value.startswith("enc:v1:") for value in rejected_email)
    resubmitted = client.post(f"/api/v1/payments/{payment_id}/receipt", headers=token,
                              files={"file": ("proof2.pdf", b"%PDF-1.7\nsecond evidence", "application/pdf")})
    assert resubmitted.status_code == 202
    review = client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                         json={"status": "PAID", "comments": "comprobante revisado"})
    assert review.status_code == 200 and review.json()["status"] == "PAID"
    assert review.json()["notification_status"] == "PENDING"
    paid_order = client.get("/api/v1/payments/my", headers=token).json()[0]
    assert paid_order["can_upload_receipt"] is False
    approved = client.post(f"/api/v1/registrations/{registration['id']}/review",
                           headers=administrator["headers"],
                           json={"status": "APPROVED", "comments": "datos correctos"})
    assert approved.status_code == 200, approved.text
    history = client.get(f"/api/v1/registrations/{registration['id']}/history?limit=10", headers=token)
    assert history.status_code == 200
    assert history.headers["x-total-count"] == "6"
    assert [entry["new_status"] for entry in history.json()] == ["PAYMENT_PENDING", "PAYMENT_REVIEW", "PAYMENT_PENDING", "PAYMENT_REVIEW", "PENDING", "APPROVED"]
    assert client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                       json={"status": "REJECTED"}).status_code == 409


def test_disabled_account_and_database_error_handling(sql_api, monkeypatch):
    ctx = sql_api
    role_id = ctx["db"].execute(text("SELECT RoleId FROM dbo.Roles WHERE Code='PARTICIPANT'")).scalar_one()
    username = f"disabled_{uuid.uuid4().hex[:8]}@gmail.com"
    ctx["db"].execute(text("""
        INSERT INTO dbo.Users(EmailCiphertext,EmailLookupHash,PasswordHash,FirstName,LastName,RoleId,IsActive)
        VALUES (:email,:lookup,:p,:first,N'Disabled',:r,0)
    """), {"email": encrypt_text(username), "lookup": email_lookup_hash(username),
          "p": hash_password("Robotics-test-password-2026"), "first": encrypt_text("Test"), "r": role_id})
    ctx["db"].commit()
    response = ctx["client"].post("/api/v1/auth/login", json={
        "email": username, "password": "Robotics-test-password-2026"})
    assert response.status_code == 401
    monkeypatch.setattr(main, "verificar_conexion", lambda: (_ for _ in ()).throw(RuntimeError("db offline")))
    assert ctx["client"].get("/api/v1/health").status_code == 503


def test_reports_aggregates_and_role_boundaries(sql_api):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"reports_{uuid.uuid4().hex[:8]}")
    registration = _create_registration(ctx, {"Authorization": f"Bearer {participant['access_token']}"})
    admin = _account(ctx, "ADMIN")
    event_manager = _account(ctx, "EVENT_MANAGER")
    administrator = _account(ctx, "ADMIN")

    url = f"?event_id={ctx['event_id']}"
    overview = client.get(f"/api/v1/reports/overview{url}", headers=admin["headers"])
    assert overview.status_code == 200, overview.text
    assert overview.json()["registrations"]["total"] == 1
    assert overview.json()["payments"]["pending_review"] == 1
    assert overview.json()["active_users"] >= 2

    statuses = client.get(f"/api/v1/reports/registrations/by-status{url}", headers=event_manager["headers"])
    assert statuses.status_code == 200, statuses.text
    assert {item["status"]: item["count"] for item in statuses.json()["items"]}["PAYMENT_PENDING"] == 1
    categories = client.get(f"/api/v1/reports/registrations/by-category{url}", headers=event_manager["headers"])
    assert categories.status_code == 200
    assert next(item for item in categories.json()["items"]
                if item["category_id"] == ctx["category_id"])["registrations"] == 1
    trend = client.get(f"/api/v1/reports/registrations/trend{url}", headers=event_manager["headers"])
    assert trend.status_code == 200 and trend.json()["items"][0]["registrations"] == 1
    registration_rows = client.get(
        f"/api/v1/reports/registrations/details{url}&page=1&limit=1",
        headers=event_manager["headers"],
    )
    assert registration_rows.status_code == 200
    assert registration_rows.json()["total"] == 1
    assert registration_rows.json()["items"][0]["registration_id"] == registration["id"]
    assert "participants" not in registration_rows.json()["items"][0]

    summary = client.get(f"/api/v1/reports/payments/summary{url}", headers=administrator["headers"])
    assert summary.status_code == 200, summary.text
    assert summary.json()["total_count"] == 1
    assert Decimal(str(summary.json()["total_amount"])) == Decimal("12.50")
    payments = client.get(f"/api/v1/reports/payments/details{url}&page=1&limit=1",
                          headers=administrator["headers"])
    assert payments.status_code == 200 and payments.json()["total"] == 1
    assert payments.json()["items"][0]["payment_id"] == registration["payment_id"]
    assert "payment_reference" not in payments.json()["items"][0]
    assert "payments" not in client.get(f"/api/v1/reports/overview{url}", headers=event_manager["headers"]).json()
    assert client.get("/api/v1/reports/payments/summary", headers=event_manager["headers"]).status_code == 403
    assert client.get("/api/v1/reports/overview", headers={"Authorization": f"Bearer {participant['access_token']}"}).status_code == 403
    assert registration["status"] == "PAYMENT_PENDING"
    assert registration["receipt_url"] == f"/api/v1/registrations/{registration['id']}/receipt"
    assert registration["email_delivery_status"] == "PENDING"
    pdf = client.get(registration["receipt_url"],
                     headers={"Authorization": f"Bearer {participant['access_token']}"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    manager = _account(ctx, "EVENT_MANAGER")
    assert client.get(registration["receipt_url"], headers=manager["headers"]).status_code == 403
    outbox = ctx["db"].execute(text("""
        SELECT o.RecipientCiphertext,o.Subject,o.BodyText,d.StorageKey,d.EncryptionVersion
        FROM dbo.EmailOutbox o JOIN dbo.RegistrationDocuments d ON d.DocumentId=o.DocumentId
        WHERE o.RegistrationId=:id
    """), {"id": registration["id"]}).mappings().one()
    assert outbox["RecipientCiphertext"].startswith("enc:v1:")
    assert outbox["Subject"].startswith("enc:v1:") and outbox["BodyText"].startswith("enc:v1:")
    assert outbox["EncryptionVersion"] == 1


def test_event_registration_config_is_role_protected_and_audited(sql_api):
    ctx = sql_api
    client = ctx["client"]
    admin = _account(ctx, "ADMIN")
    participant = _register(ctx, f"config_{uuid.uuid4().hex[:8]}")
    path = f"/api/v1/admin/events/{ctx['event_id']}/registration-config"
    payload = {
        "organization_name": "UTA SUMO CUP", "form_title": "Inscripción oficial",
        "form_description": "Formulario de prueba", "form_instructions": "Complete los datos",
        "payment_instructions": "Transferir a la cuenta institucional",
        "payment_methods": ["Transferencia", "Depósito"],
        "contact_email": "tesoreria@example.edu", "contact_phone": "0990000000",
        "receipt_message": "Conserve este documento", "currency": "USD", "is_enabled": True,
    }
    denied = client.put(path, headers={"Authorization": f"Bearer {participant['access_token']}"}, json=payload)
    assert denied.status_code == 403
    updated = client.put(path, headers=admin["headers"], json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["payment_instructions"] == payload["payment_instructions"]
    public = client.get(f"/api/v1/events/{ctx['event_id']}/registration-config")
    assert public.status_code == 200 and public.json()["payment_methods"] == payload["payment_methods"]
    assert "updated_by_user_id" not in public.json()
    history = client.get(path + "/history", headers=admin["headers"])
    assert history.status_code == 200 and history.headers["x-total-count"] == "1"
    assert history.json()[0]["current"]["payment_instructions"] == payload["payment_instructions"]


def test_email_outbox_retry_attaches_private_pdf_with_mock_smtp(sql_api, monkeypatch):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"mail_{uuid.uuid4().hex[:8]}")
    registration = _create_registration(ctx, {"Authorization": f"Bearer {participant['access_token']}"})
    outbox_id = ctx["db"].execute(text("""
        SELECT OutboxId FROM dbo.EmailOutbox WHERE RegistrationId=:id
    """), {"id": registration["id"]}).scalar_one()
    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self): pass
        def login(self, *args): pass
        def send_message(self, message): sent.append(message)

    import app.services.registration_delivery as delivery
    monkeypatch.setattr(delivery, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(delivery, "SMTP_FROM_EMAIL", "no-reply@example.test")
    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    admin = _account(ctx, "ADMIN")
    response = client.post(f"/api/v1/admin/email-outbox/{outbox_id}/retry", headers=admin["headers"])
    assert response.status_code == 200 and response.json()["status"] == "SENT"
    assert len(sent) == 1
    attachments = list(sent[0].iter_attachments())
    assert len(attachments) == 1 and attachments[0].get_content_type() == "application/pdf"
    status = ctx["db"].execute(text("""
        SELECT DeliveryStatus,Attempts FROM dbo.EmailOutbox WHERE OutboxId=:id
    """), {"id": outbox_id}).one()
    assert status == ("SENT", 1)


def test_admin_registration_list_filters_by_owner_reference_and_event(sql_api):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"admin_list_{uuid.uuid4().hex[:8]}")
    registration = _create_registration(ctx, {"Authorization": f"Bearer {participant['access_token']}"})
    admin = _account(ctx, "ADMIN")
    path = "/api/v1/admin/registrations"
    denied = client.get(path, headers={"Authorization": f"Bearer {participant['access_token']}"})
    assert denied.status_code == 403
    submitted = client.post(f"/api/v1/payments/{registration['payment_id']}/receipt",
                            headers={"Authorization": f"Bearer {participant['access_token']}"},
                            data={"payment_reference": "SUMO-TRANSFER-7788"},
                            files={"file": ("proof.pdf", b"%PDF-1.7\nevidence", "application/pdf")})
    assert submitted.status_code == 202
    query = (f"?event_id={ctx['event_id']}&payment_status=IN_REVIEW"
             f"&participant_email={participant['user']['email']}&payment_reference=SUMO-TRANSFER-7788")
    response = client.get(path + query, headers=admin["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["id"] == registration["id"]
    assert item["payment_reference"] == "SUMO-TRANSFER-7788"
    assert item["participant_email"] == participant["user"]["email"]
    assert response.headers["x-total-count"] == "1"


def test_live_scoring_is_auditable_role_protected_and_idempotent(sql_api):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"score_{uuid.uuid4().hex[:8]}")
    registration = _create_registration(ctx, {
        "Authorization": f"Bearer {participant['access_token']}"})
    ctx["db"].execute(text("""
        UPDATE dbo.Registrations SET StatusId=(SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED')
        WHERE RegistrationId=:id
    """), {"id": registration["id"]})
    ctx["db"].commit()

    manager = _account(ctx, "EVENT_MANAGER")
    changed = client.patch(f"/api/v1/events/{ctx['event_id']}/competition-status",
                           headers=manager["headers"], json={"status": "SCHEDULED"})
    assert changed.status_code == 200, changed.text
    created_round = client.post(f"/api/v1/events/{ctx['event_id']}/rounds",
                                 headers=manager["headers"], json={
                                     "category_id": ctx["category_id"],
                                     "round_number": 1, "name": "Ronda de prueba"})
    assert created_round.status_code == 201, created_round.text
    changed = client.patch(f"/api/v1/events/{ctx['event_id']}/competition-status",
                           headers=manager["headers"], json={"status": "LIVE"})
    assert changed.status_code == 200, changed.text

    payload = {"category_id": ctx["category_id"], "team_id": registration["team_id"],
               "round_id": created_round.json()["id"],
               "points_delta": 5, "reason": "Punto de prueba"}
    key = str(uuid.uuid4())
    url = f"/api/v1/events/{ctx['event_id']}/scores"
    forbidden = client.post(url, headers={"Authorization": f"Bearer {participant['access_token']}",
                                           "Idempotency-Key": key}, json=payload)
    assert forbidden.status_code == 403
    scored = client.post(url, headers={**manager["headers"], "Idempotency-Key": key}, json=payload)
    assert scored.status_code == 201, scored.text
    assert scored.json()["total_points"] == 5
    repeated = client.post(url, headers={**manager["headers"], "Idempotency-Key": key}, json=payload)
    assert repeated.status_code == 201 and repeated.json()["replayed"] is True

    correction = client.post(url, headers={**manager["headers"], "Idempotency-Key": str(uuid.uuid4())},
                             json={**payload, "points_delta": -2, "reason": "Corrección justificada"})
    assert correction.status_code == 201 and correction.json()["total_points"] == 3
    board = client.get(f"/api/v1/events/{ctx['event_id']}/leaderboard?category_id={ctx['category_id']}")
    assert board.status_code == 200 and board.json()["items"][0]["points"] == 3
    history = client.get(f"/api/v1/events/{ctx['event_id']}/scores/history?category_id={ctx['category_id']}")
    assert history.status_code == 200 and history.json()["total"] == 2
    assert "created_by" not in history.json()["items"][0]
    status_history = client.get(f"/api/v1/events/{ctx['event_id']}/competition-status/history")
    assert status_history.status_code == 200 and status_history.json()["total"] == 2
    public_audit_denied = client.get(
        f"/api/v1/events/{ctx['event_id']}/scores/audit?category_id={ctx['category_id']}",
        headers={"Authorization": f"Bearer {participant['access_token']}"})
    assert public_audit_denied.status_code == 403
    staff_audit = client.get(
        f"/api/v1/events/{ctx['event_id']}/scores/audit?category_id={ctx['category_id']}",
        headers=manager["headers"])
    assert staff_audit.status_code == 200 and staff_audit.json()["items"][0]["actor_user_id"] == manager["user_id"]
    assert client.post(url, headers={**manager["headers"], "Idempotency-Key": str(uuid.uuid4())},
                       json={**payload, "points_delta": -100}).status_code == 422


def test_current_combat_http_websocket_flow_persists_and_broadcasts(sql_api, monkeypatch):
    ctx = sql_api
    client = ctx["client"]
    registrations = []
    for index in range(2):
        participant = _register(ctx, f"combat_{index}_{uuid.uuid4().hex[:8]}")
        registration = _create_registration(ctx, {
            "Authorization": f"Bearer {participant['access_token']}"})
        ctx["db"].execute(text("""
            UPDATE dbo.Registrations
            SET StatusId=(SELECT StatusId FROM dbo.RegistrationStatuses WHERE Code='APPROVED')
            WHERE RegistrationId=:id
        """), {"id": registration["id"]})
        ctx["db"].commit()
        registrations.append(registration)

    staff = _account(ctx, "EVENT_MANAGER")
    round_response = client.post(f"/api/v1/events/{ctx['event_id']}/rounds",
        headers=staff["headers"], json={"category_id": ctx["category_id"],
        "round_number": 1, "name": "Ronda marcador"})
    assert round_response.status_code == 201, round_response.text
    match_response = client.post(f"/api/v1/events/{ctx['event_id']}/matches",
        headers=staff["headers"], json={"round_id": round_response.json()["id"],
        "match_number": 1,
        "team_ids": [item["team_id"] for item in registrations],
        "robot_ids": [item["robot_id"] for item in registrations]})
    assert match_response.status_code == 201, match_response.text

    # Use the fixture's outer transaction so this E2E test leaves no rows behind.
    from sqlalchemy.orm import Session as SqlSession
    connection = ctx["db"].connection()
    monkeypatch.setattr(competition_router, "SessionLocal", lambda: SqlSession(
        bind=connection, join_transaction_mode="create_savepoint"))
    with client.websocket_connect("/ws/combate-actual") as socket:
        initial = socket.receive_json()
        assert "estado_code" in initial and "cronometro" in initial
        if initial.get("match_id") and initial.get("estado_code") in {"EN_VIVO", "PAUSADO"}:
            finished = client.put("/api/v1/competition/combate-actual", headers=staff["headers"], json={
                "match_id": initial["match_id"], "status": "FINALIZADO",
                "reason": "Aislamiento de prueba SQL/WebSocket",
            })
            assert finished.status_code == 200, finished.text
            assert socket.receive_json() == finished.json()
        update = client.put("/api/v1/competition/combate-actual",
            headers=staff["headers"], json={
                "match_id": match_response.json()["match_id"],
                "estado": "En combate",
                "robotA": {"puntos": 2}, "robotB": {"puntos": 1},
                "detalles": "Ronda inicial", "motivo": "Marcador confirmado por juez",
            })
        assert update.status_code == 200, update.text
        response = update.json()
        assert response["estado"] == "En combate"
        assert response["robotA"]["puntos"] == 2
        assert response["robotB"]["puntos"] == 1
        assert response["detalles"] == "Ronda inicial"
        assert response["cronometro"]["enabled"] is True
        assert response["cronometro"]["direction"] == "DOWN"
        assert response["cronometro"]["status"] == "RUNNING"
        pushed = socket.receive_json()
        assert pushed == response

        match_url = "/api/v1/competition/combate-actual"
        match_paused = client.put(match_url, headers=staff["headers"], json={
            "match_id": response["match_id"], "status": "PAUSADO",
            "reason": "Pausa de prueba del cronómetro",
        })
        assert match_paused.status_code == 200, match_paused.text
        assert match_paused.json()["cronometro"]["status"] == "PAUSED"
        assert socket.receive_json() == match_paused.json()
        match_resumed = client.put(match_url, headers=staff["headers"], json={
            "match_id": response["match_id"], "status": "EN_VIVO",
            "reason": "Reanudación de prueba del cronómetro",
        })
        assert match_resumed.status_code == 200, match_resumed.text
        assert match_resumed.json()["cronometro"]["status"] == "RUNNING"
        assert socket.receive_json() == match_resumed.json()

        sleep(1.1)
        countdown_tick = client.get(match_url).json()["cronometro"]
        assert countdown_tick["current_seconds"] < response["cronometro"]["current_seconds"]

        timer_url = "/api/v1/competition/combate-actual/cronometro"
        assert client.put(timer_url, json={"enabled": True, "duration_seconds": 10}).status_code == 401
        assert client.post(f"{timer_url}/start", headers={
            "Authorization": f"Bearer {participant['access_token']}"}).status_code == 403
        configured = client.put(timer_url, headers=staff["headers"], json={
            "enabled": True, "duration_seconds": 10, "direction": "UP",
        })
        assert configured.status_code == 200, configured.text
        assert configured.json()["cronometro"]["direction"] == "UP"
        assert configured.json()["cronometro"]["status"] == "RUNNING"
        assert configured.json()["cronometro"]["current_seconds"] <= 1
        assert socket.receive_json() == configured.json()
        sleep(1.1)
        countup_tick = client.get("/api/v1/competition/combate-actual").json()["cronometro"]
        assert countup_tick["current_seconds"] > configured.json()["cronometro"]["current_seconds"]

        paused = client.post(f"{timer_url}/pause", headers=staff["headers"])
        assert paused.status_code == 200, paused.text
        assert paused.json()["cronometro"]["status"] == "PAUSED"
        assert 0 <= paused.json()["cronometro"]["current_seconds"] <= 10
        assert socket.receive_json() == paused.json()

        started = client.post(f"{timer_url}/start", headers=staff["headers"])
        assert started.status_code == 200, started.text
        assert started.json()["cronometro"]["status"] == "RUNNING"
        assert socket.receive_json() == started.json()

        reset = client.post(f"{timer_url}/reset", headers=staff["headers"])
        assert reset.status_code == 200, reset.text
        assert reset.json()["cronometro"]["status"] == "STOPPED"
        assert reset.json()["cronometro"]["current_seconds"] == 0
        assert socket.receive_json() == reset.json()

        configured_down = client.put(timer_url, headers=staff["headers"], json={
            "enabled": True, "duration_seconds": 10, "direction": "DOWN",
        })
        assert configured_down.status_code == 200, configured_down.text
        assert configured_down.json()["cronometro"]["status"] == "RUNNING"
        assert 9 <= configured_down.json()["cronometro"]["remaining_seconds"] <= 10
        assert socket.receive_json() == configured_down.json()


def test_registration_rolls_back_every_row_when_payment_insert_fails(sql_api, monkeypatch):
    ctx = sql_api
    client = ctx["client"]
    participant = _register(ctx, f"atomic_{uuid.uuid4().hex[:8]}")
    token = {"Authorization": f"Bearer {participant['access_token']}"}
    _profile, team, robot = _owned_resources(ctx, token)
    original_execute = ctx["db"].execute

    def fail_payment_insert(statement, *args, **kwargs):
        if "INSERT INTO dbo.Payments" in str(statement):
            raise SQLAlchemyError("simulated payment insert failure")
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(ctx["db"], "execute", fail_payment_insert)
    before = {
        table: ctx["db"].execute(text(f"SELECT COUNT_BIG(*) FROM dbo.{table}")).scalar_one()
        for table in ("Participants", "Registrations", "RegistrationParticipants", "Payments",
                      "StatusHistory", "RegistrationDocuments", "EmailOutbox")
    }
    with TestClient(main.app, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.post("/api/v1/registrations", headers=token, json={
            "event_id": ctx["event_id"], "category_id": ctx["category_id"],
            "team_id": team["id"], "robot_id": robot["id"],
            "participants": [
                {"role": "PARTICIPANT", "first_name": "Atomic", "last_name": "One",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
                {"role": "PARTICIPANT", "first_name": "Atomic", "last_name": "Two",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
                {"role": "COACH", "first_name": "Atomic", "last_name": "Coach",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
            ],
        })
    assert response.status_code == 503, response.text
    after = {
        table: ctx["db"].execute(text(f"SELECT COUNT_BIG(*) FROM dbo.{table}")).scalar_one()
        for table in before
    }
    assert after == before

    # Fail late, after PDF staging and metadata work, to verify the filesystem
    # artifact is removed and the database transaction remains all-or-nothing.
    storage_before = set(ctx["receipt_dir"].glob("payment-instruction-*.pdf"))

    def fail_outbox_insert(statement, *args, **kwargs):
        if "INSERT INTO dbo.EmailOutbox" in str(statement):
            raise SQLAlchemyError("simulated outbox persistence failure")
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(ctx["db"], "execute", fail_outbox_insert)
    with TestClient(main.app, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.post("/api/v1/registrations", headers=token, json={
            "event_id": ctx["event_id"], "category_id": ctx["category_id"],
            "team_id": team["id"], "robot_id": robot["id"],
            "participants": [
                {"role": "PARTICIPANT", "first_name": "Late", "last_name": "One",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
                {"role": "PARTICIPANT", "first_name": "Late", "last_name": "Two",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
                {"role": "COACH", "first_name": "Late", "last_name": "Coach",
                 "institution_id": ctx["institution_id"], "mobile_phone": None},
            ],
        })
    assert response.status_code == 503, response.text
    after_outbox_failure = {
        table: ctx["db"].execute(text(f"SELECT COUNT_BIG(*) FROM dbo.{table}")).scalar_one()
        for table in before
    }
    assert after_outbox_failure == before
    assert set(ctx["receipt_dir"].glob("payment-instruction-*.pdf")) == storage_before


def test_admin_event_forms_accounts_and_encrypted_registration_answers(sql_api):
    ctx=sql_api;client=ctx["client"]
    admin=_account(ctx,"ADMIN")
    manager=_account(ctx,"EVENT_MANAGER")
    assert client.get("/api/v1/admin/events",headers=manager["headers"]).status_code==403
    create_user=client.post("/api/v1/admin/users",headers=admin["headers"],json={
        "email":f"new_admin_{uuid.uuid4().hex[:8]}@gmail.com","first_name":"New",
        "last_name":"Admin","role":"ADMIN","password":"Strong-secret-phrase-2026!"})
    assert create_user.status_code==201,create_user.text
    assert "password" not in create_user.json()
    duplicate=client.post("/api/v1/admin/users",headers=admin["headers"],json={
        "email":create_user.json()["email"],"first_name":"New","last_name":"Admin",
        "role":"ADMIN","password":"Strong-secret-phrase-2026!"})
    assert duplicate.status_code==409

    created=client.post("/api/v1/admin/events",headers=admin["headers"],json={
        "name":f"Managed-{uuid.uuid4().hex[:8]}","edition_year":date.today().year,
        "description":"Competencia de integración","venue":"Ambato",
        "registration_start":"2026-01-01","registration_end":"2027-02-28",
        "starts_at":"2027-03-01T08:00:00","ends_at":"2027-03-01T18:00:00","is_active":True})
    assert created.status_code==201,created.text
    event_id=created.json()["id"]
    blocked_schedule=client.patch(f"/api/v1/admin/events/{event_id}/status",headers=admin["headers"],json={"status":"SCHEDULED"})
    assert blocked_schedule.status_code==409
    new_category=client.post(f"/api/v1/admin/events/{event_id}/categories",headers=admin["headers"],json={
        "name":f"Custom-{uuid.uuid4().hex[:8]}","description":"Categoría asociada al crear",
        "min_participants":1,"max_participants":2,"min_coaches":0,"max_coaches":1})
    assert new_category.status_code==201,new_category.text
    new_category_tariff=client.post("/api/v1/tariffs",headers=admin["headers"],json={
        "event_id":event_id,"category_id":new_category.json()["id"],"amount":"15.00",
        "valid_from":date.today().isoformat(),"valid_until":None,"is_active":True})
    assert new_category_tariff.status_code==201,new_category_tariff.text
    setup=client.get(f"/api/v1/admin/events/{event_id}",headers=admin["headers"])
    assert setup.status_code==200 and setup.json()["has_active_category_tariff"] is True
    assert setup.json()["registration_enabled"] is True
    scheduled=client.patch(f"/api/v1/admin/events/{event_id}/status",headers=admin["headers"],json={"status":"SCHEDULED"})
    assert scheduled.status_code==200 and scheduled.json()["status"]=="SCHEDULED"
    assert client.get(f"/api/v1/admin/events/{event_id}",headers=admin["headers"]).json()["registration_open"] is True
    invalid=client.patch(f"/api/v1/admin/events/{event_id}/status",headers=admin["headers"],json={"status":"DRAFT"})
    assert invalid.status_code==409
    update=client.put(f"/api/v1/admin/events/{event_id}",headers=admin["headers"],json={
        "name":created.json()["name"],"edition_year":date.today().year,"description":"Descripción actualizada",
        "venue":"Ambato","registration_start":"2026-01-01","registration_end":"2027-02-28",
        "starts_at":"2027-03-01T08:00:00","ends_at":"2027-03-01T18:00:00","is_active":True})
    assert update.status_code==200
    assert client.get(f"/api/v1/admin/events/{event_id}/audit",headers=admin["headers"]).json()["total"]==2
    event_detail=client.get(f"/api/v1/admin/events/{event_id}",headers=admin["headers"])
    assert any(item["id"]==new_category.json()["id"] for item in event_detail.json()["categories"])
    rules=client.put(f"/api/v1/admin/events/{event_id}/categories/{ctx['category_id']}",headers=admin["headers"],json={
        "is_active":True,"min_participants":1,"max_participants":2,"min_coaches":0,"max_coaches":1,"max_registrations":None})
    assert rules.status_code==200,rules.text
    tariff=client.post("/api/v1/tariffs",headers=admin["headers"],json={
        "event_id":event_id,"category_id":ctx["category_id"],"amount":"15.00",
        "valid_from":date.today().isoformat(),"valid_until":None,"is_active":True})
    assert tariff.status_code==201,tariff.text
    assert client.get(f"/api/v1/admin/events/{event_id}/tariffs",headers=admin["headers"]).json()["items"][0]["amount"]==15.0

    form_body={"title":"Formulario","description":"Datos extra","fields":[
        {"id":"school","label":"Institución","type":"short_text","required":True,"options":[]}]}
    form=client.put(f"/api/v1/admin/events/{ctx['event_id']}/form",headers=admin["headers"],json=form_body)
    assert form.status_code==200,form.text
    assert client.get(f"/api/v1/events/{ctx['event_id']}/form").json()["version"]==1

    participant=_register(ctx,f"custom_{uuid.uuid4().hex[:8]}")
    token={"Authorization":f"Bearer {participant['access_token']}"}
    profile,team,robot=_owned_resources(ctx,token)
    body={"event_id":ctx["event_id"],"category_id":ctx["category_id"],"team_id":team["id"],
          "robot_id":robot["id"],"participants":[{"participant_id":profile["id"],"role":"PARTICIPANT"}]}
    missing=client.post("/api/v1/registrations",headers=token,json=body)
    assert missing.status_code==422
    body["custom_answers"]={"school":"Universidad de prueba"}
    registration=client.post("/api/v1/registrations",headers=token,json=body)
    assert registration.status_code==201,registration.text
    detail=client.get(f"/api/v1/registrations/{registration.json()['id']}",headers=token)
    assert detail.status_code==200
    assert detail.json()["custom_answers"]==body["custom_answers"]
    assert detail.json()["custom_form_version"]==1
    stored=ctx["db"].execute(text("SELECT AnswersCiphertext FROM dbo.RegistrationFormResponses WHERE RegistrationId=:id"),
                              {"id":registration.json()["id"]}).scalar_one()
    assert stored.startswith("enc:v1:") and body["custom_answers"]["school"] not in stored
    form_body["title"]="Formulario v2"
    form2=client.put(f"/api/v1/admin/events/{ctx['event_id']}/form",headers=admin["headers"],json=form_body)
    assert form2.status_code==200 and form2.json()["version"]==2
    assert client.get(f"/api/v1/registrations/{registration.json()['id']}",headers=token).json()["custom_form_version"]==1
