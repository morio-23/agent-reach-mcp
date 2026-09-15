# Codex local verification

This checklist is intentionally mechanical. Run it in order; only investigate or edit code if a step fails.

## 1. Install

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e '.[dev]'
```

## 2. Offline/contract checks

```bash
python -m compileall -q src tests scripts
ruff check .
pytest -q
python scripts/local_verify.py
```

Expected MCP tool names:

```text
get_capabilities
read_url
search_x
get_x_user_posts
get_x_post
get_youtube_transcript
```

## 3. Agent Reach/backend health

```bash
agent-reach doctor
```

If X is configured, verify the upstream CLI independently before blaming MCP:

```bash
twitter user-posts OpenAI --max 2 --json
```

## 4. Streamable HTTP smoke test

Terminal A:

```bash
agent-reach-mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

Terminal B:

```bash
python scripts/http_verify.py
```

Expected: protocol version, six tools, and `get_capabilities: OK`.

## 5. Static bearer auth

Terminal A:

```powershell
$env:AGENT_REACH_MCP_AUTH_MODE="static_token"
$env:AGENT_REACH_MCP_STATIC_TOKEN="local-test-secret"
agent-reach-mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

Terminal B:

```bash
python scripts/http_verify.py --token local-test-secret
```

Also confirm a wrong token is rejected:

```bash
python scripts/http_verify.py --token wrong-token
```

The last command is expected to fail authentication.

## 6. Optional live content checks

These depend on network access and upstream service state, so do not treat a third-party outage as an implementation failure.

Use an MCP client/Inspector to call:

- `read_url` with a public HTTPS page.
- `get_x_user_posts` after twitter-cli credentials are confirmed.
- `get_x_post` with a known public post.
- `search_x` with a small limit; X search itself can be less stable than user-posts.
- `get_youtube_transcript` with a public video known to have subtitles.

## 7. OAuth scope

Do not stand up a new identity provider just for this verification. OAuth mode is a resource-server implementation and requires an existing issuer/JWKS. Verify it later against the deployment's actual Keycloak/Auth0/Entra configuration.

## Codex instruction

Use this exact task to minimize reasoning/token usage:

> On branch `feature/initial-mcp-foundation`, follow `CODEX_VERIFY.md` in order. Do not redesign or refactor. Only fix concrete failures encountered during local verification. Do not run GitHub Actions. After checks pass, report the commands run, results, any fixes made, and remaining live-backend limitations. Commit and push only fixes that were required by failed checks; otherwise make no code changes.
