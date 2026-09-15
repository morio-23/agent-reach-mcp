# agent-reach-mcp

Read-only remote MCP gateway for [Agent Reach](https://github.com/Panniantong/Agent-Reach), designed for ChatGPT and other MCP clients.

> Status: v0.1 development. Private until the initial API and OSS release shape are stable.

## Initial tools

- `get_capabilities`
- `read_url`
- `search_x`
- `get_x_user_posts`
- `get_x_post`
- `get_youtube_transcript`

No shell, arbitrary CLI, write operations, credential retrieval, or unrestricted local-file access is exposed.

## Development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
python scripts/local_verify.py
```

`local_verify.py` uses the MCP SDK's in-process client, lists all tools and calls `get_capabilities` without needing ChatGPT.

## Streamable HTTP

```bash
AGENT_REACH_MCP_TRANSPORT=streamable-http \
AGENT_REACH_MCP_HOST=127.0.0.1 \
AGENT_REACH_MCP_PORT=8080 \
agent-reach-mcp
```

Endpoint: `http://127.0.0.1:8080/mcp`.

Unauthenticated HTTP cannot bind to a non-loopback address unless `AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE=true` is explicitly set.

## ChatGPT

ChatGPT connects to a remote MCP endpoint rather than directly to local stdio. For a private/home-server deployment, prefer loopback `Streamable HTTP` behind OpenAI Secure MCP Tunnel. For a public HTTPS deployment, use OAuth/OIDC.

See [`docs/chatgpt.md`](docs/chatgpt.md) for the deployment and connection guide.

Current ChatGPT custom-MCP availability depends on plan and workspace policy. The server remains usable with other MCP clients even when ChatGPT custom-app access is unavailable for the current account.

## Authentication

`AGENT_REACH_MCP_AUTH_MODE` supports:

- `none` — stdio, localhost or a private/tunneled deployment.
- `static_token` — simple Bearer token for generic/private MCP clients.
- `oauth` — JWT resource-server validation for an external OAuth/OIDC authorization server.

For ChatGPT, prefer the supported no-auth/private-tunnel or OAuth path rather than assuming that a custom static Bearer token can be entered in the ChatGPT app configuration UI.

OAuth mode does **not** implement an authorization server. Use Keycloak/Auth0/Entra/etc. and configure:

```env
AGENT_REACH_MCP_AUTH_MODE=oauth
AGENT_REACH_MCP_PUBLIC_BASE_URL=https://mcp.example.com
AGENT_REACH_MCP_OAUTH_ISSUER=https://auth.example.com/realms/agent-reach
AGENT_REACH_MCP_OAUTH_AUDIENCE=agent-reach-mcp
AGENT_REACH_MCP_OAUTH_SCOPES=agent-reach:read
```

JWT signatures are checked through OIDC discovery/JWKS (or `AGENT_REACH_MCP_OAUTH_JWKS_URL`).

## X

The first implementation uses Agent Reach's `twitter-cli` path. The gateway invokes it with an argv array, `shell=False`, a timeout, JSON output and a response-size limit. Explicit Agent Reach Twitter credentials are injected only into that child process and are never returned to MCP clients.

Examples of underlying live checks before MCP testing:

```bash
agent-reach doctor
twitter user-posts OpenAI --max 2 --json
```

## YouTube

`get_youtube_transcript` uses existing manual/automatic subtitles via `yt-dlp`. Audio transcription fallback is deliberately not automatic because it may invoke external ASR providers and introduce privacy/cost implications.

## Security

Retrieved web/social/video content is untrusted data. It is returned as data and is never interpreted server-side as instructions.

The gateway also validates URLs/handles, rejects arbitrary commands, applies backend timeouts and size limits, and scrubs errors before returning them through MCP.

## Current limitations

- X automatic OpenCLI fallback is not implemented yet.
- OAuth supports JWT access tokens; opaque-token introspection is not implemented yet.
- Live backend availability depends on the user's Agent Reach setup.
- ChatGPT custom-MCP access depends on the user's current ChatGPT plan/workspace policy.

## Relationship to Agent Reach

Agent Reach remains responsible for capability setup and backend configuration. This project is an independently maintained MCP facade and is not affiliated with Agent Reach maintainers.

## License

MIT
