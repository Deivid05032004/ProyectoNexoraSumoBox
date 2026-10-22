"""Opt-in end-to-end SQL Server tests. All SQL is rolled back per fixture."""
import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import main
import routers.competition as competition_router
import routers.payments as payments_router
import routers.auth as auth_router
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
    monkeypatch.setattr(auth_router, "EMAIL_CHECK_DELIVERABILITY", False)
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
        "name": f"Robot-{uuid.uuid4().hex[:8]}", "robot_description": "test robot",
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
    registration = _create_registration(ctx, token)
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
    submitted = client.post(f"/api/v1/payments/{payment_id}/receipt", headers=token,
                            data={"payment_reference": "bank-transfer-test"},
                            files={"file": ("proof.pdf", b"%PDF-1.7\nmock evidence", "application/pdf")})
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
    rejected = client.post(f"/api/v1/payments/{payment_id}/review", headers=administrator["headers"],
                           json={"status": "REJECTED", "comments": "evidencia ilegible"})
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
    history = client.get(f"/api/v1/registrations/{registration['id']}/history", headers=token)
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
        assert initial["estado_code"] == "SIN_COMBATE_ACTIVO"
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
        pushed = socket.receive_json()
        assert pushed == response


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
