import pytest
from pydantic import ValidationError

from agent_reach_mcp.config import AuthMode, Settings, TransportMode


def test_defaults_are_local_stdio() -> None:
    settings = Settings(_env_file=None)
    assert settings.transport is TransportMode.STDIO
    assert settings.auth_mode is AuthMode.NONE
    assert settings.host == "127.0.0.1"


def test_none_auth_rejects_remote_http_by_default() -> None:
    with pytest.raises(ValidationError):
        Settings(transport=TransportMode.STREAMABLE_HTTP, host="0.0.0.0", _env_file=None)


def test_none_auth_can_explicitly_allow_remote_http() -> None:
    settings = Settings(transport=TransportMode.STREAMABLE_HTTP, host="0.0.0.0", allow_insecure_remote=True, _env_file=None)
    assert settings.allow_insecure_remote is True


def test_static_token_requires_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode=AuthMode.STATIC_TOKEN, _env_file=None)


def test_oauth_requires_issuer_audience_and_public_url() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode=AuthMode.OAUTH, _env_file=None)

    settings = Settings(
        auth_mode=AuthMode.OAUTH,
        oauth_issuer="https://auth.example.com",
        oauth_audience="agent-reach-mcp",
        public_base_url="https://mcp.example.com",
        _env_file=None,
    )
    assert settings.mcp_url == "https://mcp.example.com/mcp"
