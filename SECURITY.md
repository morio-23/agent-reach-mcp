# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest `main` branch and the latest published release when releases exist.

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability that could expose credentials, bypass authentication, enable command execution, access local files, or make authenticated upstream services reachable by unauthorized users.

Use GitHub's private vulnerability reporting / Security Advisory flow for this repository when available. If private reporting is not available, contact the maintainer privately before publishing technical details.

Include:

- affected commit/version;
- deployment mode (`stdio`, private Streamable HTTP, public OAuth deployment, etc.);
- reproduction steps;
- impact;
- whether any real credentials were exposed;
- suggested mitigation if known.

Do not include live cookies, access tokens, OAuth tokens, or other secrets in reports.

## Security model

`agent-reach-mcp` is intentionally read-only at the MCP surface. It must not expose arbitrary shell/CLI execution, unrestricted file reads, credential retrieval, or write actions to external platforms.

Retrieved internet content is untrusted data and must never be interpreted by the server as instructions.

Upstream credentials remain server-side. X credentials, when configured, are passed only to the selected child process and must not be returned through MCP responses or logs.

## Deployment expectations

- Private/home deployments should bind to loopback and use a supported private tunnel.
- Public deployments should use HTTPS and OAuth/OIDC.
- `AUTH_MODE=none` on a non-loopback interface is blocked unless explicitly overridden.
- Static bearer auth is intended for generic/private MCP clients and should not be treated as equivalent to a full OAuth deployment.
- Reverse proxies/tunnels must not inject trusted identity headers unless the deployment explicitly implements and validates such a trust boundary.

## Out of scope

Issues caused solely by an upstream service outage, upstream API breakage, expired user credentials, or platform rate limits are not security vulnerabilities unless they can be leveraged to cross this project's security boundary.
