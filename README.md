# agent-reach-mcp

Remote MCP gateway for [Agent Reach](https://github.com/Panniantong/Agent-Reach), designed for ChatGPT and other MCP clients. Read operations are the default; X posting is an explicit opt-in.

> Status: v0.1 pre-release. Install from source; PyPI publication is not currently supported because the official Agent Reach dependency is pinned to GitHub source.

## Initial tools

- `get_capabilities`
- `read_url`
- `search_x`
- `get_x_user_posts`
- `get_x_post`
- `post_x` (only when `AGENT_REACH_MCP_X_WRITE_ENABLED=true`)
- `get_youtube_transcript`

No shell, arbitrary CLI, credential retrieval, or unrestricted local-file access is exposed. X write access is absent by default and is exposed only when explicitly enabled.

## Development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
python scripts/local_verify.py
```

Install the optional X backend when you want to use the X tools from a source checkout:

```bash
pip install -e '.[x]'
```

For development with X enabled, install both extras:

```bash
pip install -e '.[dev,x]'
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

For a persistent Linux/WSL2 service, see [`docs/self-hosting.md`](docs/self-hosting.md).

## Docker

The container image includes the optional X backends (`twitter-cli` and Twifork) and Agent Reach's YouTube dependency. The image itself remains fail-closed: unauthenticated `0.0.0.0` listening is rejected unless the deployment explicitly opts into a private container boundary or configures authentication.

Private loopback-only example:

```bash
docker compose -f compose.private.yml build
docker compose -f compose.private.yml up -d
python scripts/http_verify.py
```

`compose.private.yml` publishes the MCP port only on host `127.0.0.1` and persists Agent Reach configuration in a named volume at `/home/appuser/.agent-reach`.

To configure X credentials interactively inside that persisted volume, use Agent Reach's manual Cookie-Editor flow rather than baking credentials into the image:

```bash
docker compose -f compose.private.yml run --rm --entrypoint agent-reach \
  agent-reach-mcp configure twitter-cookies
```

Never commit or copy the resulting Agent Reach configuration into the image.

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

The primary X read path uses Agent Reach's `twitter-cli`. When `AGENT_REACH_MCP_X_TWIFORK_FALLBACK_ENABLED=true` (the default), read failures can fall back to Twifork using the same explicitly configured `auth_token` and `ct0` cookies. The gateway keeps twitter-cli as the primary backend and reports the backend that served each result.

Optional X posting is deliberately off by default. Set `AGENT_REACH_MCP_X_WRITE_ENABLED=true` to expose `post_x`; each call must also pass `confirm=true`. The write path uses Twifork and supports plain-text posts/replies plus 1-4 attached images supplied as public HTTPS URLs. Images are downloaded with a 5 MiB per-image limit, restricted to PNG/JPEG/WebP. DNS targets are rejected unless they resolve only to public IP addresses, and HTTPS connections are pinned to the validated numeric address while TLS certificate verification uses the original URL hostname. Optional `media_alt_texts` can be supplied in the same order as `media_urls`. Local file paths are not exposed through MCP. Do not enable write tools on a broadly shared or insufficiently authenticated MCP endpoint.

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

- Twifork is a fallback for the current X read tools; it is not a full automatic backend router for every X operation.
- X posting supports plain-text posts/replies and up to four PNG/JPEG/WebP images from public HTTPS URLs. Video/GIF upload and delete/like/repost actions are not exposed.
- OAuth supports JWT access tokens; opaque-token introspection is not implemented yet.
- Live backend availability depends on the user's Agent Reach setup.
- ChatGPT custom-MCP access depends on the user's current ChatGPT plan/workspace policy.
- Source/PyPI packaging still depends on a pinned upstream Agent Reach GitHub commit; PyPI publication is intentionally not claimed yet.

## Relationship to Agent Reach

Agent Reach remains responsible for capability setup and backend configuration. This project is an independently maintained MCP facade and is not affiliated with Agent Reach maintainers.

## License

MIT
