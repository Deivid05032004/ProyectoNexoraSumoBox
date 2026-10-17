"""Google OpenID Connect ID-token verification."""

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token


class InvalidGoogleToken(ValueError):
    pass


def verify_google_id_token(token: str, client_id: str) -> dict:
    """Verify signature, issuer, expiry and audience using Google's client library."""
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID no está configurado.")
    try:
        claims = id_token.verify_oauth2_token(token, Request(), audience=client_id)
    except (GoogleAuthError, ValueError, TypeError) as exc:
        raise InvalidGoogleToken from exc

    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise InvalidGoogleToken
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") is not True:
        raise InvalidGoogleToken
    return claims
