from __future__ import annotations


class GatewayError(RuntimeError):
    """Base error safe to surface to an MCP client after scrubbing."""


class BackendUnavailableError(GatewayError):
    """The required Agent Reach backend is not installed or configured."""


class BackendExecutionError(GatewayError):
    """A backend failed while processing a read-only request."""
