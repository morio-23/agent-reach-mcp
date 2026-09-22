# Codex dogfood verification

Use this only after the maintainer has entered real X credentials with the interactive Agent Reach Cookie-Editor flow. Do not ask for, print, copy, or inspect credential values.

## Goal

Verify the real Streamable HTTP MCP path with minimal code changes and minimal token use.

## Commands

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q

docker compose -f compose.private.yml build
docker compose -f compose.private.yml up -d
python scripts/http_verify.py
python scripts/dogfood_live.py

docker compose -f compose.private.yml restart
python scripts/dogfood_live.py
```

## Rules

- Do not run GitHub Actions.
- Do not redesign or refactor the gateway.
- Do not modify authentication or tool schemas unless a concrete dogfood failure proves it is necessary.
- Do not expose or log X cookies/tokens.
- Do not run `twitter` directly as a substitute for the MCP test; the intended boundary is Agent Reach config -> agent-reach-mcp child-only environment -> twitter-cli.
- If a command fails, identify whether it is gateway code, upstream X/YouTube/network behavior, or local environment first.
- Make only the smallest code/configuration fix needed for a reproducible gateway defect.
- Commit/push only when code or tracked docs actually change.

## Report only

1. compileall / ruff / pytest results
2. first dogfood run result by step
3. restart dogfood run result by step
4. whether X worked without re-entering cookies after restart
5. any concrete gateway defect and minimal fix
6. commit SHA if a fix was pushed
7. whether the gateway is ready for normal maintainer use before v0.1 release

Do not include fetched content or credential values in the report.
