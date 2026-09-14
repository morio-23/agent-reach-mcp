from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str] = frozenset()


class AuthProvider(Protocol):
    async def authenticate(self, headers: Mapping[str, str]) -> Principal:
        """Authenticate one MCP HTTP request and return its principal."""
        ...


class AnonymousAuthProvider:
    async def authenticate(self, headers: Mapping[str, str]) -> Principal:
        return Principal(subject="anonymous")
