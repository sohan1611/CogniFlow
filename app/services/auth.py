"""Verification of Neon Auth account tokens.

Only public signing keys are handled here.  Tokens are accepted solely from the
configured Neon Auth origin and are never included in errors or logs.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import jwt


JWKS_CACHE_SECONDS = 10 * 60
UNKNOWN_KID_REFRESH_SECONDS = 60
CLOCK_LEEWAY_SECONDS = 30


@dataclass(frozen=True)
class Account:
    user_id: str
    name: str | None
    email: str | None


class AuthError(Exception):
    """A safe, short reason why authentication was refused."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _default_fetch_jwks(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JWKS document is not an object")
    return payload


class TokenVerifier:
    def __init__(
        self,
        base_url: str,
        fetch_jwks: Callable[[str], dict] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("NEON_AUTH_BASE_URL must be an absolute HTTP(S) URL")

        self._jwks_url = f"{base_url.rstrip('/')}/.well-known/jwks.json"
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._fetch_jwks = fetch_jwks or _default_fetch_jwks
        self._clock = clock
        self._cached_jwks: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._last_unknown_kid_refresh = float("-inf")
        self._lock = threading.Lock()

    def verify(self, token: str) -> Account:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("malformed token") from exc

        # Algorithm confusion: an attacker must never substitute none, HMAC, or any
        # algorithm that can reinterpret public key material as a shared secret.
        if header.get("alg") != "EdDSA":
            raise AuthError("unsupported signing algorithm")

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthError("missing signing key id")

        # Remote-key injection: jku, x5u, and embedded jwk headers are deliberately
        # ignored; key material comes only from the configured Neon JWKS endpoint.
        key = self._key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["EdDSA"],
                issuer=self._origin,
                audience=self._origin,
                leeway=CLOCK_LEEWAY_SECONDS,
                options={
                    "require": ["exp", "iat", "sub"],
                    "strict_aud": True,
                    # PyJWT uses wall-clock time internally. These three claims are
                    # checked below so the injected clock controls both expiry and
                    # cache behaviour with the same strict 30-second leeway.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.MissingRequiredClaimError as exc:
            raise AuthError(f"missing {exc.claim} claim") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthError("invalid issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError("invalid audience") from exc
        except jwt.InvalidSignatureError as exc:
            raise AuthError("invalid signature") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid token") from exc

        # Replay window: exp, iat, and optional nbf are evaluated with exactly 30
        # seconds of skew, never an open-ended or library-default tolerance.
        self._validate_times(claims)

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("invalid subject")
        name = claims.get("name")
        email = claims.get("email")
        return Account(
            user_id=subject,
            name=name if isinstance(name, str) else None,
            email=email if isinstance(email, str) else None,
        )

    def _key_for(self, kid: str) -> Any:
        with self._lock:
            now = self._clock()
            # Stale-key risk: ordinary JWKS data lives for only ten minutes before a
            # fresh copy is required from the one configured source.
            if self._cached_jwks is None or now - self._cached_at >= JWKS_CACHE_SECONDS:
                self._cached_jwks = self._fetch()
                self._cached_at = now

            jwk = self._find_jwk(self._cached_jwks, kid)
            if jwk is None and now - self._last_unknown_kid_refresh >= UNKNOWN_KID_REFRESH_SECONDS:
                # Rotation abuse: an unknown kid gets one refresh, rate-limited so
                # garbage key IDs cannot amplify into an outbound-request flood.
                self._last_unknown_kid_refresh = now
                self._cached_jwks = self._fetch()
                self._cached_at = now
                jwk = self._find_jwk(self._cached_jwks, kid)

            if jwk is None:
                raise AuthError("unknown signing key")

            try:
                # Key-type confusion: Neon signing keys are only OKP Ed25519 keys.
                if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
                    raise ValueError("unexpected JWK type")
                return jwt.PyJWK(jwk).key
            except Exception as exc:  # noqa: BLE001 - malformed remote keys fail closed
                raise AuthError("invalid signing key") from exc

    def _fetch(self) -> dict[str, Any]:
        try:
            payload = self._fetch_jwks(self._jwks_url)
            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                raise ValueError("invalid JWKS document")
            return payload
        except AuthError:
            raise
        except Exception as exc:
            # Fail closed: a key-service outage refuses the request and never falls
            # through to an unsigned or previously unverified accept path.
            raise AuthError("JWKS fetch failed") from exc

    @staticmethod
    def _find_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
        for candidate in jwks.get("keys", []):
            if isinstance(candidate, dict) and candidate.get("kid") == kid:
                return candidate
        return None

    def _validate_times(self, claims: dict[str, Any]) -> None:
        try:
            expires_at = float(claims["exp"])
            issued_at = float(claims["iat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("invalid time claim") from exc
        if not math.isfinite(expires_at) or not math.isfinite(issued_at):
            raise AuthError("invalid time claim")

        now = self._clock()
        if expires_at <= now - CLOCK_LEEWAY_SECONDS:
            raise AuthError("token expired")
        if issued_at > now + CLOCK_LEEWAY_SECONDS:
            raise AuthError("token issued in the future")

        if "nbf" in claims:
            try:
                not_before = float(claims["nbf"])
            except (TypeError, ValueError) as exc:
                raise AuthError("invalid not-before claim") from exc
            if not math.isfinite(not_before) or not_before > now + CLOCK_LEEWAY_SECONDS:
                raise AuthError("token not yet valid")
