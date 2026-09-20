# Local operator console (MVP)

The console is a **separate, local-only** screen for using AgentReach without
requiring ChatGPT to execute MCP tools. It registers X usernames, X search queries and Web page URLs. X retrieval
uses the existing twitter-cli / Twifork adapter; Web retrieval uses the existing
read_url gateway. A platform-neutral library deduplicates by platform and
external ID, with reusable tags, collections, review state and notes.

**Scope in this PR:** source registration/removal, manual investigation,
backend/warning display, generic item library, free-form tags/collections,
status-based review and durable storage. **Not in this PR:** X posting,
posting drafts, automated posting, scheduled collection, RSS/YouTube source
registration, change-history tracking, or any external application registration.
The existing MCP deployment remains read-only.

## Deploy on Windows / Docker Desktop

Make sure your existing MCP and Cloudflare Tunnel still run as before. The
console uses a **separate loopback-only port**, does not change the MCP's
`/mcp` route, and does not become a Cloudflare published hostname.

1. Update the local `main` branch. In a terminal in the repository root,
   generate an independent random dashboard access token:

   ```powershell
   $consoleKey = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
   ```

2. Add the following to the existing Git-ignored `.env` file **locally**
   (replace the example token with `$consoleKey`; don't paste it into chat):

   ```dotenv
   AGENT_REACH_MCP_HOST_PORT=8085
   AGENT_REACH_CONSOLE_HOST_PORT=8090
   AGENT_REACH_CONSOLE_ACCESS_TOKEN=your-own-random-64-hex-character-key
   ```

   Preserve `CLOUDFLARE_TUNNEL_TOKEN` and existing settings. The console
   access key is distinct from the Tunnel token and X cookies.

3. Start **only** the new service, leaving the running MCP and tunnel alone:

   ```powershell
   docker compose -f compose.private.yml -f compose.console.yml up -d --build agent-reach-console
   docker compose -f compose.private.yml -f compose.console.yml ps
   docker compose -f compose.private.yml -f compose.console.yml logs --tail=30 agent-reach-console
   ```

4. Open **http://127.0.0.1:8090/** on this Windows PC. Enter the access
   token from your local `.env`. The page does not store the token in browser
   storage or cookies; it stays in memory until the page closes or reloads.

5. Register `LoveLive_staff` as an X username, `ラブライブ` as an X
   search query or `https://example.com/news` as a Web page URL. Click
   `調査する`, then add tags, collections, review status and notes in the
   library. Existing sources and reviews are migrated automatically, once.
   X and Web remain separately identifiable; the original tables are retained
   for rollback. A repeated fetch of the same URL currently keeps the first
   stored snapshot rather than updating its body; change history is future work.

The console uses the same persisted `agent-reach-data` volume as MCP for
AgentReach's manually configured X credentials; it stores its own SQLite DB at
`/home/appuser/.agent-reach/console.sqlite3`. It never copies credentials to
the UI. Removing the console service does not remove existing source or
review data, unless you explicitly delete the volume. **Do not run
`docker compose down -v`**.

The console is published only to `127.0.0.1` on the Windows host. Its API
requires a separate high-entropy console token and checks the request host
and origin. Do not add `agent-reach-console:8090` to any Cloudflare Tunnel
published route. Do not open port 8090 through a firewall or router. This is
not a multi-user, internet-exposed administration UI.

## Verify without CI

```powershell
pytest -q
ruff check .
python scripts/local_verify.py
docker compose -f compose.private.yml -f compose.console.yml config --quiet
python scripts/http_verify.py --url http://127.0.0.1:8085/mcp
```

Then test username/query/URL registration, X and Web investigation, tag and
collection persistence, filters, and review persistence after reload. The
existing source and finding records must still be visible after the upgrade. Check that the
published ChatGPT MCP continues exposing **six read-only tools** and that
`https://mcp.morio-23.net/mcp` remains protected by Cloudflare Access.

This is a manually triggered console: it deliberately does not scrape X
periodically, retry failed posting, or publish calendar events.

### Data structure

`sources` and `findings` are the legacy tables and are not deleted.
`source_registry` contains X usernames, X queries and Web page URLs.
`library_items` stores a platform-neutral item ID (`x:<post-id>` or a
`web:` ID derived from the canonical page URL). Separate tables store free-form
tags and named collections. This makes the same item reusable across workflows
without tying it to OshiCalendar. The Web URL is verified by the existing
Gateway.read_url path before it is fetched; do not interpret this console as a
general network proxy.

For this MVP, investigation is manually triggered for one source or a
bounded batch of **1–5 selected sources** (sequentially; max 10 posts per X
source). Failure of one source is shown in the per-source results and the
remaining sources continue; backend exception details are not sent to the
browser. The 50 most recent run outcomes are retained (10 shown on screen).
The latest 300 matching library items are returned, with 20 rendered at a
time. A Web source represents a single page, not a domain crawl or RSS poll.

The library marks a freshly ingested item as `new`; when its captured body
changes, the previous and new bodies are saved as a revision and it is marked
`updated`. An unchanged refetch does not reset the review, tags, collections
or notes. These change labels represent **the most recent detected content
change**, not "new since the last UI visit", and pre-upgrade records are
initially marked `existing`. Revision display is intentionally capped; large
pages may still need a more specialized text-diff UI later. Changes to X post
metadata alone are not treated as body updates. Scheduling, paginated backend
fetching, workflow-specific extraction and export adapters are future work.
