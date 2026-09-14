# agent-reach-mcp

Remote MCP gateway for [Agent Reach](https://github.com/Panniantong/Agent-Reach), designed for ChatGPT and other MCP clients.

> Status: early development. The repository is currently private while the public OSS shape is stabilized.

## Goals

- Expose Agent Reach capabilities through stable, intent-oriented MCP tools.
- Support remote MCP clients such as ChatGPT without exposing arbitrary shell execution.
- Normalize backend-specific output into predictable structured results.
- Keep authentication optional and pluggable.
- Remain a thin facade so upstream Agent Reach can evolve independently.

## Non-goals

- Reimplement Agent Reach backends.
- Expose arbitrary command execution, shell access, cookies, API keys, or local files.
- Become an identity provider. OAuth deployments should validate tokens issued by an external authorization server.

## Planned MCP tools

### v0.1

- `get_capabilities`
- `read_url`
- `search_x`
- `get_x_user_posts`
- `get_x_post`
- `get_youtube_transcript`

Additional platforms will be added after the initial schemas stabilize.

## Authentication modes

`agent-reach-mcp` is designed to support multiple deployment patterns:

- `none` — local development or a private/tunneled deployment.
- `static_token` — simple bearer token for generic MCP clients.
- `oauth` — recommended for an internet-exposed remote MCP server.
- `trusted_proxy` — reserved for deployments protected by an upstream access gateway.

The default is `none`, but unauthenticated non-loopback HTTP listening is rejected unless explicitly allowed.

## Security model

Internet content is untrusted data. This gateway does not execute instructions found in retrieved content.

The MCP surface intentionally does **not** provide tools such as `exec`, `shell`, `run_command`, arbitrary CLI execution, credential retrieval, or unrestricted local file access.

Backend processes must be invoked with argument arrays rather than `shell=True`, and adapters will enforce timeouts, result limits, and output-size limits.

## Architecture

```text
ChatGPT / MCP client
        |
        | MCP (stdio for development, Streamable HTTP for remote use)
        v
+---------------------------+
| agent-reach-mcp           |
|                           |
| MCP tools                 |
| auth providers            |
| validation / limits       |
| output normalization      |
| capability routing        |
+-------------+-------------+
              |
              v
         Agent Reach
              |
       upstream backends
```

## Development

Requirements:

- Python 3.10+
- Agent Reach and any upstream backends required for the capabilities you want to use

Install in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run tests:

```bash
pytest
```

Run the MCP server over stdio:

```bash
agent-reach-mcp
```

Remote Streamable HTTP support is part of the v0.1 implementation plan.

## Configuration

Configuration is environment-variable based. Planned variables include:

```env
AGENT_REACH_MCP_AUTH_MODE=none
AGENT_REACH_MCP_HOST=127.0.0.1
AGENT_REACH_MCP_PORT=8080
AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE=false

# static_token mode
AGENT_REACH_MCP_STATIC_TOKEN=

# oauth mode
AGENT_REACH_MCP_OAUTH_ISSUER=
AGENT_REACH_MCP_OAUTH_AUDIENCE=
```

Secrets must never be committed to the repository.

## Relationship to Agent Reach

Agent Reach remains responsible for installing, configuring, and checking the capabilities/backends it supports. This project provides a safe, stable MCP-facing facade over those capabilities.

Agent Reach is MIT licensed. This project is independently maintained and is not affiliated with the Agent Reach maintainers.

## License

MIT
