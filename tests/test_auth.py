"""Account-token verification and API ownership boundaries.

Every key is generated in memory and every JWKS fetcher is injected. These tests never
contact Neon or any other network service.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app.api.main import SESSIONS, app
from app.services.auth import Account, AuthError, TokenVerifier
from app.services.student_store import StudentStore


BASE_URL = "https://auth.example.test/neondb/auth"
ORIGIN = "https://auth.example.test"
NOW = 1_800_000_000.0
KID = "test-key"
USER_ID = "9cf5b38b-3bc6-4e8f-9c66-09739dad1711"


def _key_pair(kid: str = KID) -> tuple[Ed25519PrivateKey, dict[str, str], bytes]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    encoded = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
    jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "use": "sig",
        "alg": "EdDSA",
        "kid": kid,
        "x": encoded,
    }
    return private_key, jwk, public_bytes


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": USER_ID,
        "id": USER_ID,
        "name": "Account Learner",
        "email": "learner@example.test",
        "iat": NOW,
        "exp": NOW + 300,
        "iss": ORIGIN,
        "aud": ORIGIN,
    }
    claims.update(overrides)
    return claims


def _token(
    private_key: Ed25519PrivateKey,
    *,
    kid: str = KID,
    claims: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    token_headers = {"kid": kid, **(headers or {})}
    return jwt.encode(claims or _claims(), private_key, algorithm="EdDSA", headers=token_headers)


def _verifier(
    jwk: dict[str, str],
    *,
    fetch: Callable[[str], dict] | None = None,
    clock: Callable[[], float] = lambda: NOW,
) -> TokenVerifier:
    return TokenVerifier(
        BASE_URL,
        fetch_jwks=fetch or (lambda _url: {"keys": [jwk]}),
        clock=clock,
    )


def test_valid_token_returns_account() -> None:
    private_key, jwk, _ = _key_pair()

    account = _verifier(jwk).verify(_token(private_key))

    assert account == Account(
        user_id=USER_ID,
        name="Account Learner",
        email="learner@example.test",
    )


def test_expired_token_is_rejected() -> None:
    private_key, jwk, _ = _key_pair()
    token = _token(private_key, claims=_claims(exp=NOW - 31))

    with pytest.raises(AuthError, match="expired"):
        _verifier(jwk).verify(token)


@pytest.mark.parametrize("claim", ["iat", "exp"])
def test_required_time_claims_are_rejected_when_missing(claim: str) -> None:
    private_key, jwk, _ = _key_pair()
    claims = _claims()
    del claims[claim]

    with pytest.raises(AuthError, match=f"missing {claim} claim"):
        _verifier(jwk).verify(_token(private_key, claims=claims))


def test_wrong_issuer_is_rejected() -> None:
    private_key, jwk, _ = _key_pair()

    with pytest.raises(AuthError, match="issuer"):
        _verifier(jwk).verify(_token(private_key, claims=_claims(iss="https://elsewhere.test")))


def test_wrong_audience_is_rejected() -> None:
    private_key, jwk, _ = _key_pair()

    with pytest.raises(AuthError, match="audience"):
        _verifier(jwk).verify(_token(private_key, claims=_claims(aud="another-service")))


def test_tampered_signature_is_rejected() -> None:
    private_key, jwk, _ = _key_pair()
    encoded_header, encoded_payload, signature = _token(private_key).split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = ".".join((encoded_header, encoded_payload, replacement + signature[1:]))

    with pytest.raises(AuthError, match="signature"):
        _verifier(jwk).verify(tampered)


def test_none_algorithm_is_rejected() -> None:
    _, jwk, _ = _key_pair()
    token = jwt.encode(_claims(), key="", algorithm="none", headers={"kid": KID})

    with pytest.raises(AuthError, match="algorithm"):
        _verifier(jwk).verify(token)


def test_hs256_signed_with_public_key_bytes_is_rejected() -> None:
    _, jwk, public_bytes = _key_pair()
    token = jwt.encode(_claims(), public_bytes, algorithm="HS256", headers={"kid": KID})

    with pytest.raises(AuthError, match="algorithm"):
        _verifier(jwk).verify(token)


def test_jku_header_is_ignored() -> None:
    private_key, jwk, _ = _key_pair()
    fetched: list[str] = []

    def fetch(url: str) -> dict:
        fetched.append(url)
        return {"keys": [jwk]}

    token = _token(
        private_key,
        headers={"jku": "https://attacker.invalid/keys.json"},
    )

    assert _verifier(jwk, fetch=fetch).verify(token).user_id == USER_ID
    assert fetched == [f"{BASE_URL}/.well-known/jwks.json"]


def test_unknown_kid_refetches_once_and_is_then_rate_limited() -> None:
    first_private, first_jwk, _ = _key_pair("first")
    rotated_private, rotated_jwk, _ = _key_pair("rotated")
    third_private, _, _ = _key_pair("third")
    documents = [{"keys": [first_jwk]}, {"keys": [rotated_jwk]}]
    fetch_count = 0

    def fetch(_url: str) -> dict:
        nonlocal fetch_count
        document = documents[min(fetch_count, len(documents) - 1)]
        fetch_count += 1
        return document

    verifier = _verifier(first_jwk, fetch=fetch)
    assert verifier.verify(_token(first_private, kid="first")).user_id == USER_ID
    assert verifier.verify(_token(rotated_private, kid="rotated")).user_id == USER_ID
    assert fetch_count == 2, "the rotated kid should cause exactly one refresh"

    with pytest.raises(AuthError, match="unknown signing key"):
        verifier.verify(_token(third_private, kid="third"))
    assert fetch_count == 2, "another unknown kid inside 60 seconds must not refetch"


def test_jwks_fetch_failure_is_an_auth_error() -> None:
    private_key, jwk, _ = _key_pair()

    def failed_fetch(_url: str) -> dict:
        raise OSError("key service unavailable")

    with pytest.raises(AuthError, match="JWKS fetch failed"):
        _verifier(jwk, fetch=failed_fetch).verify(_token(private_key))


@pytest.fixture
def account_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, Path]:
    import app.api.main as api

    private_key, jwk, _ = _key_pair()
    verifier = _verifier(jwk)
    token = _token(private_key)
    db = tmp_path / "account-api.db"
    monkeypatch.setattr(api, "StudentStore", lambda *args, **kwargs: StudentStore(db))
    monkeypatch.setattr(api, "token_verifier", lambda: verifier)
    SESSIONS.clear()
    return TestClient(app), token, db


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_account_mode_rejects_a_missing_header(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, _, _ = account_client

    response = client.post("/session", json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "Please sign in again."}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_account_mode_rejects_a_garbage_token(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, _, _ = account_client

    response = client.post("/session", json={}, headers=_authorization("not-a-jwt"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Please sign in again."}


def test_account_session_uses_the_token_subject(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, token, db = account_client

    response = client.post("/session", json={}, headers=_authorization(token))

    assert response.status_code == 200
    assert response.json()["student_id"] == USER_ID
    assert StudentStore(db).exists(USER_ID)
    assert SESSIONS[USER_ID].display_name == "Account Learner"


def test_another_accounts_student_and_session_routes_are_forbidden(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, token, _ = account_client
    headers = _authorization(token)
    client.post("/session", json={}, headers=headers)

    student_response = client.get("/student/someone-else/progress", headers=headers)
    session_response = client.get("/session/someone-else/diagnostic", headers=headers)

    for response in (student_response, session_response):
        assert response.status_code == 403
        assert response.json() == {
            "detail": "That progress belongs to a different account."
        }


def test_own_student_and_session_routes_are_accessible(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, token, _ = account_client
    headers = _authorization(token)
    client.post("/session", json={}, headers=headers)

    assert client.get(f"/student/{USER_ID}/progress", headers=headers).status_code == 200
    assert client.get(f"/session/{USER_ID}/diagnostic", headers=headers).status_code == 200


def test_health_and_skills_stay_public_in_account_mode(
    account_client: tuple[TestClient, str, Path],
) -> None:
    client, _, _ = account_client

    health = client.get("/health")
    skills = client.get("/skills")

    assert health.status_code == 200
    assert health.json()["auth"] == "required"
    assert skills.status_code == 200


def test_name_mode_stays_compatible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.main as api

    db = tmp_path / "name-api.db"
    monkeypatch.setattr(api, "StudentStore", lambda *args, **kwargs: StudentStore(db))
    monkeypatch.setattr(api, "token_verifier", lambda: None)
    SESSIONS.clear()
    client = TestClient(app)

    assert client.get("/health").json()["auth"] == "off"
    response = client.post("/session", json={"name": "Aarav"})
    assert response.status_code == 200
    assert response.json()["student_id"] == "aarav"

    missing = client.post("/session", json={})
    blank = client.post("/session", json={"name": ""})
    assert missing.status_code == blank.status_code == 422
    assert missing.json()["detail"][0]["loc"] == ["body", "name"]
    assert blank.json()["detail"][0]["loc"] == ["body", "name"]
