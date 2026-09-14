from enum import Enum
from ipaddress import ip_address

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthMode(str, Enum):
    NONE = "none"
    STATIC_TOKEN = "static_token"
    OAUTH = "oauth"
    TRUSTED_PROXY = "trusted_proxy"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_REACH_MCP_",
        env_file=".env",
        extra="ignore",
    )

    auth_mode: AuthMode = AuthMode.NONE
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    allow_insecure_remote: bool = False

    static_token: str | None = None
    oauth_issuer: str | None = None
    oauth_audience: str | None = None

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.auth_mode is AuthMode.STATIC_TOKEN and not self.static_token:
            raise ValueError("static_token auth requires AGENT_REACH_MCP_STATIC_TOKEN")

        if self.auth_mode is AuthMode.OAUTH:
            if not self.oauth_issuer or not self.oauth_audience:
                raise ValueError(
                    "oauth auth requires AGENT_REACH_MCP_OAUTH_ISSUER and "
                    "AGENT_REACH_MCP_OAUTH_AUDIENCE"
                )

        if (
            self.auth_mode is AuthMode.NONE
            and not self.allow_insecure_remote
            and not _is_loopback_host(self.host)
        ):
            raise ValueError(
                "unauthenticated remote listening is disabled; bind to a loopback host, "
                "enable authentication, or explicitly set "
                "AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE=true"
            )

        return self


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
