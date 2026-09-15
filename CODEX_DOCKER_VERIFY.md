# Codex Docker verification

This is intentionally mechanical and low-token. Do not redesign or refactor before running the provided verifier.

## Preconditions

- Branch: `feature/oss-readiness`
- Docker Engine / Docker Desktop is running.
- The project development virtual environment is available with `pip install -e '.[dev]'` completed.
- Do not run GitHub Actions.

## Run

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q
python scripts/docker_verify.py
```

`docker_verify.py` automatically uses a temporary loopback port and a dedicated Compose project. It verifies:

- Compose parsing;
- Docker image build;
- default unauthenticated `0.0.0.0` startup fails closed;
- private Compose startup;
- host port is published only on `127.0.0.1`;
- `twitter-cli` and `yt-dlp` exist in the clean image;
- the container runs as non-root;
- `/home/appuser/.agent-reach` is writable through the named volume;
- MCP Streamable HTTP initialization and `get_capabilities` work;
- temporary containers/network/volume are cleaned up.

Do not configure real X cookies for this verification. Live X credential persistence can be checked separately when intentionally testing authenticated X access.

## Codex instruction

Use this exact task:

> On `morio-23/agent-reach-mcp` branch `feature/oss-readiness`, run the commands in `CODEX_DOCKER_VERIFY.md` in order. Do not redesign, refactor, or run GitHub Actions. If all commands pass, make no code changes and report the results. If a command fails, identify the concrete cause and make only the minimum fix necessary, then rerun the failed check and the full `python scripts/docker_verify.py`. Commit and push only required fixes. Do not add unrelated features.
