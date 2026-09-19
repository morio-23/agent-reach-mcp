# ChatGPT remote connection

This project is a read-only MCP gateway for Agent Reach. ChatGPT connects to remote MCP servers; it does not connect directly to a local stdio server.

## Supported deployment shapes

### 1. Private/local server through Secure MCP Tunnel

Recommended for a developer machine, home server, or private network.

```text
ChatGPT
   |
   | Secure MCP Tunnel
   v
127.0.0.1:8080/mcp
   |
agent-reach-mcp
```

Run the MCP server locally with no application-level auth and bind it only to loopback:

```bash
AGENT_REACH_MCP_TRANSPORT=streamable-http \
AGENT_REACH_MCP_AUTH_MODE=none \
AGENT_REACH_MCP_HOST=127.0.0.1 \
AGENT_REACH_MCP_PORT=8080 \
agent-reach-mcp
```

Do not set `AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE=true` for this deployment.

The tunnel is responsible for making the loopback endpoint reachable by supported OpenAI products without exposing the server directly to the public internet.

### 2. Public HTTPS endpoint with OAuth/OIDC

Recommended for a persistent internet-accessible deployment.

```text
ChatGPT
   |
   | HTTPS + OAuth
   v
https://mcp.example.com/mcp
   |
agent-reach-mcp
```

Example:

```env
AGENT_REACH_MCP_TRANSPORT=streamable-http
AGENT_REACH_MCP_AUTH_MODE=oauth
AGENT_REACH_MCP_HOST=0.0.0.0
AGENT_REACH_MCP_PORT=8080
AGENT_REACH_MCP_PUBLIC_BASE_URL=https://mcp.example.com
AGENT_REACH_MCP_OAUTH_ISSUER=https://auth.example.com/realms/agent-reach
AGENT_REACH_MCP_OAUTH_AUDIENCE=agent-reach-mcp
AGENT_REACH_MCP_OAUTH_SCOPES=agent-reach:read
```

The authorization server is external. `agent-reach-mcp` validates JWT access tokens and does not implement user login, password storage, authorization-code issuance, or refresh-token storage.

For long-lived ChatGPT connections, configure the external OAuth/OIDC provider to support refresh tokens / offline access as required by the provider and ChatGPT.

### 3. Cloudflare Tunnel + Access Managed OAuth (Docker)

For the existing Windows/Docker Desktop deployment, use the **optional**
[Cloudflare Tunnel guide](cloudflare-tunnel.md) instead of exposing the local
port. This is a separate authentication boundary: a restricted Cloudflare
Access application performs the client's interactive OAuth flow at the edge,
while the private MCP origin retains `AUTH_MODE=none`. Do not set up a public
route before Access is enabled, and do not enable write tools in this setup.
The MCP origin does not yet validate Cloudflare Access JWT assertion headers;
see the guide for the security limitations.

## Static token mode

`static_token` remains supported for generic MCP clients and private integrations:

```env
AGENT_REACH_MCP_AUTH_MODE=static_token
AGENT_REACH_MCP_STATIC_TOKEN=replace-me
```

Do not document this as the preferred ChatGPT authentication path. ChatGPT custom-app setup should use its supported no-auth/private-tunnel or OAuth flow.

## ChatGPT setup

Current ChatGPT custom MCP availability depends on plan and workspace policy. In ChatGPT Web, enable Developer Mode where available, create a custom app, enter the remote MCP endpoint, select the applicable authentication method, scan tools, and create the app.

Expected tools:

- `get_capabilities`
- `read_url`
- `search_x`
- `get_x_user_posts`
- `get_x_post`
- `get_youtube_transcript`

The server intentionally exposes read-only tools only.

## Pre-flight checks

Before adding the endpoint to ChatGPT, verify locally:

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q
python scripts/local_verify.py
```

Then verify Streamable HTTP:

```bash
agent-reach-mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

In another shell:

```bash
python scripts/http_verify.py
```

## Backend notes

### X

The X tools require `twitter-cli` plus explicit `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` credentials. Credential values stay on the server and are never returned through MCP.

### YouTube

`get_youtube_transcript` uses existing manual/automatic subtitles through yt-dlp. It does not automatically upload audio to an external transcription provider.

### Web

`read_url` uses Agent Reach/Jina Reader and accepts only normalized public HTTP(S) URLs.

## Security checklist

- Prefer loopback + Secure MCP Tunnel for a private server.
- If exposing the endpoint publicly, terminate TLS and require OAuth.
- Never expose shell or arbitrary CLI execution as an MCP tool.
- Never pass cookies, access tokens, or upstream credentials in MCP tool arguments.
- Treat all fetched content as untrusted data.
- Keep request timeouts and output-size limits enabled.
- Review your upstream platform terms before enabling platform-specific adapters.
