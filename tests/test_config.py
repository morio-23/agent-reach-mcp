import pytest
from pydantic import ValidationError

from agent_reach_mcp.config import AuthMode, Settings


def test_default_config_is_loopback_and_unauthenticated() -> None:
    settings = Settings(_env_file=None)

    assert settings.auth_mode is AuthMode.NONE
    assert settings.host == "127.0.0.1"


def test_none_auth_rejects_remote_listen_by_default() -> None:
    with pytest.raises(ValidationError):
        Settings(host="0.0.0.0", _env_file=None)


def test_none_auth_can_explicitly_allow_remote_listen() -> None:
    settings = Settings(
        host="0.0.0.0",
        allow_insecure_remote=True,
        _env_file=None,
    )

    assert settings.allow_insecure_remote is True


def test_static_token_requires_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode=AuthMode.STATIC_TOKEN, _env_file=None)


def test_oauth_requires_issuer_and_audience() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode=AuthMode.OAUTH, _env_file=None)

    settings = Settings(
        auth_mode=AuthMode.OAUTH,
        oauth_issuer="https://auth.example.com",
        oauth_audience="agent-reach-mcp",
        _env_file=None,
    )

    assert settings.oauth_issuer == "https://auth.example.com"
