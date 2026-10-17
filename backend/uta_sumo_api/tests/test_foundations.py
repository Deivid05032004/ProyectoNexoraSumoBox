from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password, verify_password
from main import app


def test_password_hash_round_trip_and_not_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_rejects_over_1024_utf8_bytes():
    try:
        hash_password("ñ" * 513)
    except ValueError:
        return
    raise AssertionError("Expected byte-length validation")


def test_live_health_does_not_depend_on_sql_server():
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_exposes_server_pagination_metadata():
    with TestClient(app) as client:
        response = client.get("/api/v1/registrations", headers={
            "Origin": "http://localhost:5173",
        })
    assert response.status_code == 401
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "x-total-count" in exposed and "x-total-pages" in exposed


def test_registration_rejects_client_supplied_privileged_role():
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/register", json={
            "email": "someone@example.com", "password": "valid-password",
            "first_name": "First", "last_name": "Last", "institution_id": 1,
            "role": "ADMIN",
        })
    assert response.status_code == 422


def test_registration_requires_valid_email_and_strong_password():
    with TestClient(app) as client:
        invalid_email = client.post("/api/v1/auth/register", json={
            "email": "not-an-email", "password": "A secure passphrase 2026!",
            "first_name": "First", "last_name": "Last", "institution_id": 1,
        })
        weak_password = client.post("/api/v1/auth/register", json={
            "email": "someone@example.com", "password": "passwordpassword",
            "first_name": "First", "last_name": "Last", "institution_id": 1,
        })
    assert invalid_email.status_code == 422
    assert weak_password.status_code == 422


def test_google_identity_verifies_id_token_with_configured_audience(monkeypatch):
    from app.services import google_identity

    expected = {"iss": "https://accounts.google.com", "sub": "google-sub-123",
                "email": "person@gmail.com", "email_verified": True}
    calls = []

    def fake_verify(token, request, audience):
        calls.append((token, audience))
        return expected

    monkeypatch.setattr(google_identity.id_token, "verify_oauth2_token", fake_verify)
    assert google_identity.verify_google_id_token("signed-google-id-token", "client-id") == expected
    assert calls == [("signed-google-id-token", "client-id")]


def test_google_identity_rejects_unverified_email(monkeypatch):
    from app.services import google_identity

    monkeypatch.setattr(google_identity.id_token, "verify_oauth2_token", lambda *args, **kwargs: {
        "iss": "https://accounts.google.com", "sub": "google-sub-123",
        "email": "person@gmail.com", "email_verified": False,
    })
    try:
        google_identity.verify_google_id_token("signed-google-id-token", "client-id")
    except google_identity.InvalidGoogleToken:
        return
    raise AssertionError("Expected an unverified Google email to be rejected")


def test_google_login_requires_server_client_id(monkeypatch):
    import routers.auth as auth_router

    monkeypatch.setattr(auth_router, "GOOGLE_CLIENT_ID", "")
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/google", json={
            "id_token": "x" * 120, "institution_id": 1,
        })
    assert response.status_code == 503


def test_expired_bearer_token_is_rejected():
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.core.config import ALGORITHM, SECRET_KEY

    expired = jwt.encode({"sub": "1", "role": "PARTICIPANT",
                          "exp": datetime.now(timezone.utc)-timedelta(minutes=1)},
                         SECRET_KEY, algorithm=ALGORITHM)
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_access_token_contains_subject_and_role(monkeypatch):
    from jose import jwt
    import app.core.config as config
    import app.core.security as security

    secret = "unit-test-secret-key-with-at-least-32-chars"
    monkeypatch.setattr(config, "SECRET_KEY", secret)
    monkeypatch.setattr(security, "SECRET_KEY", secret)
    claims = jwt.decode(create_access_token(42, "PARTICIPANT"), secret,
                        algorithms=[config.ALGORITHM])
    assert claims["sub"] == "42"
    assert claims["role"] == "PARTICIPANT"


def test_receipt_limit_rejects_oversized_chunked_body():
    import asyncio

    from main import ReceiptUploadSizeLimit

    async def run():
        called = False
        output = []
        chunks = [
            {"type": "http.request", "body": b"x" * 150_000, "more_body": True},
            {"type": "http.request", "body": b"y" * 112_145, "more_body": False},
        ]

        async def receive():
            return chunks.pop(0)

        async def send(message):
            output.append(message)

        async def inner(scope, receive, send):
            nonlocal called
            called = True

        middleware = ReceiptUploadSizeLimit(inner, max_bytes=0)
        scope = {"type": "http", "method": "POST", "path": "/api/v1/payments/5/receipt", "headers": []}
        await middleware(scope, receive, send)
        return called, output

    called, output = asyncio.run(run())
    assert not called
    assert output[0]["status"] == 413
