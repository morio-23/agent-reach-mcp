# Dogfooding before v0.1 release

Do not tag a release only because unit tests and container smoke tests pass. Before v0.1, run the gateway against the real sources you actually depend on.

The dogfood path deliberately exercises the **running Streamable HTTP MCP endpoint**, not the adapters directly.

## 1. Prepare a private profile

Create an untracked profile:

```bash
mkdir -p .dogfood
cp dogfood.example.json .dogfood/profile.json
```

Edit `.dogfood/profile.json` so it represents a real task you care about:

- `read_url`: a site you actually read;
- `x.username`: an X account you actually monitor;
- `x.query`: a search term expected to return results for that account;
- `youtube.url`: a captioned video you actually want to read, or keep the known-captioned example while validating the transport.

`.dogfood/` is ignored by git. Do not put cookies or tokens in the profile. If the endpoint uses static bearer auth, set `token_env` to the **name** of an environment variable containing the token; do not put the token value in JSON.

## 2. Build the private container

```bash
docker compose -f compose.private.yml build
```

The compose file publishes only host `127.0.0.1:8080` and persists Agent Reach configuration in a named volume.

## 3. Configure X credentials once

Use Agent Reach's hidden interactive Cookie-Editor flow inside the same Compose volume:

```bash
docker compose -f compose.private.yml run --rm --entrypoint agent-reach \
  agent-reach-mcp configure twitter-cookies
```

Follow the prompt. Do not pass `TWITTER_AUTH_TOKEN` or `TWITTER_CT0` as command-line arguments and do not commit the resulting Agent Reach configuration.

Agent Reach intentionally does not export those values into your shell. `agent-reach-mcp` reads the saved Agent Reach config and injects the two values only into its `twitter-cli` child process.

## 4. Start the MCP service

```bash
docker compose -f compose.private.yml up -d
python scripts/http_verify.py
```

## 5. Run the real dogfood profile

From the project virtual environment:

```bash
python scripts/dogfood_live.py
```

A full X-enabled run checks:

- MCP protocol/tool discovery;
- `get_capabilities`;
- `read_url` returns non-empty content;
- `get_x_user_posts` returns posts;
- `get_x_post` can read the first returned post (or `x.post` from the profile);
- `search_x` executes the configured real search;
- `get_youtube_transcript` returns non-empty subtitles.

The script writes only operational summaries such as item counts, content character counts, backend names, warnings, and elapsed time to `.dogfood/runs/*.json`. It does not persist fetched post/page/transcript bodies.

## 6. Verify X credential persistence

Restart the container without re-entering credentials:

```bash
docker compose -f compose.private.yml restart
python scripts/dogfood_live.py
```

The X tools must still pass. This proves the named Agent Reach volume survives a normal service restart.

## Release gate

Do not tag v0.1 until all of the following are true:

- one full X-enabled dogfood run passes;
- the same profile passes after a container restart without entering cookies again;
- at least one additional real-world task is completed through the MCP surface rather than by calling an upstream CLI directly;
- any friction discovered during those runs is either fixed or documented as an intentional limitation;
- no dogfood output contains credentials or other local secrets.

Real OAuth/ChatGPT connectivity can be evaluated separately when the target client/account supports it. The release gate here is about proving the gateway itself is useful for the maintainer's actual read-only workflow.
