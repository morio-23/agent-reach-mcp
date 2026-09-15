import asyncio
import hmac
import json
import urllib.request
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from .config import AuthMode, Settings

_DISCOVERY_MAX_BYTES = 1024 * 1024

class StaticTokenVerifier(TokenVerifier):
    def __init__(self, expected_token: str, resource: str):
        self._expected_token = expected_token
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._expected_token):
            return None
        return AccessToken(token=token, client_id="static-token-client", scopes=[], subject="static-token-user", resource=self._resource)

@dataclass
class OAuthJWTVerifier(TokenVerifier):
    issuer: str
    audience: str
    resource: str
    algorithms: list[str]
    jwks_url: str | None = None
    timeout_seconds: float = 10.0

    def __post_init__(self):
        self._jwks_client: PyJWKClient | None = None

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await asyncio.to_thread(self._verify_sync, token)
        except Exception:
            return None

    def _verify_sync(self, token: str) -> AccessToken:
        signing_key = self._get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(token, signing_key.key, algorithms=self.algorithms, audience=self.audience, issuer=self.issuer, options={"require": ["exp", "iss", "aud"]})
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or claims.get("sub") or "oauth-client"),
            scopes=_extract_scopes(claims),
            expires_at=int(claims["exp"]),
            resource=self.resource,
            subject=str(claims["sub"]) if claims.get("sub") is not None else None,
            claims={"iss": claims.get("iss")},
        )

    def _get_jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url or _discover_jwks_url(self.issuer, self.timeout_seconds), timeout=self.timeout_seconds)
        return self._jwks_client

def build_auth(settings: Settings) -> tuple[TokenVerifier | None, AuthSettings | None]:
    if settings.auth_mode is AuthMode.NONE:
        return None, None
    resource = settings.mcp_url
    if settings.auth_mode is AuthMode.STATIC_TOKEN:
        assert settings.static_token
        verifier: TokenVerifier = StaticTokenVerifier(settings.static_token, resource)
        issuer = "https://static-token.invalid"
        required_scopes: list[str] = []
    else:
        assert settings.oauth_issuer and settings.oauth_audience
        verifier = OAuthJWTVerifier(settings.oauth_issuer, settings.oauth_audience, resource, settings.oauth_algorithms, settings.oauth_jwks_url)
        issuer = settings.oauth_issuer
        required_scopes = settings.oauth_scopes
    return verifier, AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
        required_scopes=required_scopes,
        validate_token_resource=True,
    )

def _extract_scopes(claims: dict[str, Any]) -> list[str]:
    raw = claims.get("scope")
    if isinstance(raw, str):
        return [x for x in raw.split() if x]
    raw = claims.get("scp")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        return [x for x in raw.split() if x]
    return []

def _discover_jwks_url(issuer: str, timeout_seconds: float) -> str:
    req = urllib.request.Request(issuer.rstrip("/") + "/.well-known/openid-configuration", headers={"Accept": "application/json", "User-Agent": "agent-reach-mcp/0.1"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read(_DISCOVERY_MAX_BYTES + 1)
    if len(body) > _DISCOVERY_MAX_BYTES:
        raise ValueError("OIDC discovery document is too large")
    jwks_uri = json.loads(body.decode("utf-8")).get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
        raise ValueError("OIDC discovery document does not contain an HTTPS jwks_uri")
    return jwks_uri
