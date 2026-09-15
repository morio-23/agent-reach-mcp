import pytest

from agent_reach_mcp.auth import StaticTokenVerifier, build_auth
from agent_reach_mcp.config import Settings


@pytest.mark.asyncio
async def test_static_token_verifier() -> None:
    verifier = StaticTokenVerifier("secret", "http://127.0.0.1:8080/mcp")
    assert await verifier.verify_token("wrong") is None
    token = await verifier.verify_token("secret")
    assert token is not None
    assert token.client_id == "static-token-client"
    assert token.resource == "http://127.0.0.1:8080/mcp"


def test_no_auth_builds_no_verifier() -> None:
    verifier, auth = build_auth(Settings(_env_file=None))
    assert verifier is None
    assert auth is None


def test_static_token_enables_resource_validation() -> None:
    verifier, auth = build_auth(
        Settings(_env_file=None, auth_mode="static_token", static_token="secret")
    )
    assert verifier is not None
    assert auth is not None
    assert auth.validate_token_resource is True
    assert auth.required_scopes == []


def test_oauth_uses_jwt_audience_validation() -> None:
    verifier, auth = build_auth(
        Settings(
            _env_file=None,
            auth_mode="oauth",
            oauth_issuer="https://auth.example.com",
            oauth_audience="agent-reach-mcp",
            public_base_url="https://mcp.example.com",
        )
    )
    assert verifier is not None
    assert auth is not None
    assert auth.validate_token_resource is False
    assert auth.required_scopes == ["agent-reach:read"]
