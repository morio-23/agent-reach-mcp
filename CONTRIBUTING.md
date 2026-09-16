# Contributing

Thanks for considering a contribution to `agent-reach-mcp`.

## Project principles

- Keep the MCP surface read-only unless a future major design explicitly changes that policy.
- Prefer intent-oriented tools over exposing backend command syntax.
- Never expose arbitrary shell execution, unrestricted file access, cookies, tokens, or local credentials.
- Treat fetched content as untrusted data.
- Keep Agent Reach/backend-specific behavior behind adapters so upstream implementations can change independently.
- Preserve stable normalized result schemas where practical.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e '.[dev]'
```

Run local checks:

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q
python scripts/local_verify.py
```

For Streamable HTTP verification:

```bash
agent-reach-mcp --transport streamable-http --host 127.0.0.1 --port 8080
```

Then in another shell:

```bash
python scripts/http_verify.py
```

## Pull requests

Keep changes focused. Include tests for behavior changes and document new environment variables or public MCP tool/schema changes.

Do not include credentials, local paths, cookies, browser profiles, private URLs, or captured production payloads.

For backend-dependent changes, distinguish gateway bugs from upstream service/tool failures in the PR description.

## New MCP tools

A new tool should:

- be read-only;
- have a narrow, typed input schema;
- validate limits and identifiers;
- enforce timeouts/output-size limits where it calls an upstream process or network service;
- return normalized structured output;
- scrub backend errors before surfacing them;
- avoid exposing backend command strings as the public API.

## Authentication changes

Authentication code is security-sensitive. Changes should include tests covering rejection cases and should preserve safe defaults for unauthenticated remote listening.

The project acts as a resource server for OAuth deployments; it should not grow into a password store or general-purpose identity provider.
