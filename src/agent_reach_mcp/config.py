from enum import Enum
from ipaddress import ip_address
from urllib.parse import urljoin
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AuthMode(str, Enum):
    NONE = "none"
    STATIC_TOKEN = "static_token"
    OAUTH = "oauth"

class TransportMode(str, Enum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_REACH_MCP_", env_file=".env", extra="ignore")
    transport: TransportMode = TransportMode.STDIO
    auth_mode: AuthMode = AuthMode.NONE
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    mcp_path: str = "/mcp"
    public_base_url: str | None = None
    allow_insecure_remote: bool = False
    static_token: str | None = None
    oauth_issuer: str | None = None
    oauth_audience: str | None = None
    oauth_jwks_url: str | None = None
    oauth_scopes: list[str] = Field(default_factory=lambda: ["agent-reach:read"])
    oauth_algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_output_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_text_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    capabilities_cache_ttl_seconds: float = Field(default=60.0, ge=0, le=3600)

    @field_validator("mcp_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/") or "?" in value or "#" in value:
            raise ValueError("mcp_path must be an absolute URL path")
        return value.rstrip("/") or "/"

    @field_validator("oauth_scopes", "oauth_algorithms", mode="before")
    @classmethod
    def csv_list(cls, value):
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return value

    @model_validator(mode="after")
    def validate_security(self):
        if self.auth_mode is AuthMode.STATIC_TOKEN and not self.static_token:
            raise ValueError("static_token auth requires AGENT_REACH_MCP_STATIC_TOKEN")
        if self.auth_mode is AuthMode.OAUTH:
            missing = [n for n, v in (("AGENT_REACH_MCP_OAUTH_ISSUER", self.oauth_issuer), ("AGENT_REACH_MCP_OAUTH_AUDIENCE", self.oauth_audience), ("AGENT_REACH_MCP_PUBLIC_BASE_URL", self.public_base_url)) if not v]
            if missing:
                raise ValueError("oauth auth requires " + ", ".join(missing))
        if self.transport is TransportMode.STREAMABLE_HTTP and self.auth_mode is AuthMode.NONE and not self.allow_insecure_remote and not _is_loopback_host(self.host):
            raise ValueError("unauthenticated remote listening is disabled")
        return self

    @property
    def mcp_url(self) -> str:
        if self.public_base_url:
            return urljoin(self.public_base_url.rstrip("/") + "/", self.mcp_path.lstrip("/"))
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}{self.mcp_path}"

def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
