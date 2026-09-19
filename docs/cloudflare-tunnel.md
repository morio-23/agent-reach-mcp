# Cloudflare Tunnel for the private Docker deployment

This is an **opt-in** deployment for a domain hosted on Cloudflare. It keeps the
existing local HTTP endpoint (8085 on Windows in the example) and adds a
`cloudflared` container on the same private Compose network. Cloudflare
configuration, the tunnel token, and DNS are **not** created by this repository.

> **Do not publish an unprotected route.** Cloudflare Tunnel provides a network
> path, not authentication. Configure an Access application restricted to your
> own identity, with **Managed OAuth** for an MCP client, before creating the
> public route. Keep `post_x` disabled.

## Architecture

```text
ChatGPT --HTTPS/OAuth--> Cloudflare Access --Tunnel--> cloudflared (Compose)
                                                  |
                                      http://agent-reach-mcp:8080
                                                  |
                                  agent-reach-mcp (private Docker network)
                                                  |
                      Windows: http://127.0.0.1:8085/mcp (local diagnostics)
```

`8085` is the **Windows host** port. The tunnel sidecar runs **inside Docker**
and therefore targets `http://agent-reach-mcp:8080`, **not**
`http://localhost:8085` or `http://127.0.0.1:8085`. The existing Compose
file continues to publish only on the Windows loopback address.

## 1. Keep the local server working

From the repository root in PowerShell, with Docker Desktop running:

```powershell
git switch main
docker compose -f compose.private.yml ps
python scripts/http_verify.py --url http://127.0.0.1:8085/mcp
```

If your local host port is different, use the actual port. Avoid changing or
removing the existing Agent Reach named volume: it contains manually imported
credentials. Do **not** run `docker compose down -v`.

## 2. Create a remotely managed tunnel

In Cloudflare, first confirm that the purchased domain is active in your account.

1. Go to **Networking > Tunnels** and create a remotely managed Cloudflare
   Tunnel, e.g. `agent-reach-mcp`. Select the Docker installation instructions.
2. Copy only its **tunnel token** into the **local, Git-ignored** repository
   `.env` file. Never paste the token into a chat, issue, commit, screenshot,
   or a Compose command:

   ```dotenv
   AGENT_REACH_MCP_HOST_PORT=8085
   CLOUDFLARE_TUNNEL_TOKEN=replace-with-your-actual-tunnel-token
   ```

   If `.env` already exists, append/update only those two keys; preserve other
   local configuration. If port 8085 is already set elsewhere, leave the
   existing correct value. `.env` is excluded by `.gitignore`.

3. Create an **Access self-hosted application** for your chosen hostname,
   such as `mcp.your-domain.example`, with an **Allow** policy restricted to
   your own email/identity and a deny-by-default policy. Enable **Managed OAuth**
   under its advanced settings, and restrict permitted redirect URIs to the
   MCP client you plan to use. Do not enable a bypass/Everyone policy.

   Ordinary browser-only Access login can redirect MCP clients to a login
   page rather than provide an OAuth challenge. Managed OAuth is designed to
   let compatible clients authenticate through Access. This deployment relies
   on Access enforcing policy **at the Cloudflare edge**; the current MCP
   application does **not** validate the `Cf-Access-Jwt-Assertion` header.
   Keep the origin reachable only through the Access-protected route or the
   Windows loopback address. Do not use this configuration as a general
   internet-facing origin without additional application-layer authentication.

4. Only **after the Access application is configured**, add the tunnel's
   **Published application** route:
   - Hostname: the same `mcp.your-domain.example`.
   - Service URL: **`http://agent-reach-mcp:8080`**.
   - Path: leave blank (route the entire hostname, including `/mcp` and
     OAuth discovery endpoints).
   - Do not point the route at `localhost` or at port `8085`.

   Cloudflare creates the corresponding proxied DNS record for the hostname.
   No router port-forwarding or incoming firewall opening is required.

The hostname above is an **example**, not an already configured domain.
The eventual ChatGPT MCP URL is `https://YOUR-HOSTNAME/mcp`.

## 3. Start the optional sidecar

Use **both** Compose files for all tunnel-specific operations:

```powershell
docker compose -f compose.private.yml -f compose.cloudflare.yml config --quiet
docker compose -f compose.private.yml -f compose.cloudflare.yml up -d
docker compose -f compose.private.yml -f compose.cloudflare.yml ps
docker compose -f compose.private.yml -f compose.cloudflare.yml logs --tail=80 cloudflared
python scripts/http_verify.py --url http://127.0.0.1:8085/mcp
```

`compose.cloudflare.yml` is optional; running `compose.private.yml` alone
does not start the tunnel. The sidecar has no published host ports. If the
Docker image needs updating, run `docker compose -f compose.private.yml -f
compose.cloudflare.yml pull cloudflared` and then `up -d`.

The tunnel connection being healthy only proves that `cloudflared` can reach
Cloudflare; it does **not** prove that the Access policy, route or MCP
initialization works.

## 4. Verify the access boundary **before** connecting ChatGPT

From a terminal **without an Access login/session**, request your actual URL:

```powershell
curl.exe -i -H "Accept: application/json" https://YOUR-HOSTNAME/mcp
```

Access must reject/challenge this unauthenticated request; it must not allow
normal MCP tool discovery. A normal unauthenticated browser GET against MCP
is not a sufficient protocol test by itself, so also verify the actual
Access-protected OAuth flow from your MCP client. `http_verify.py` is a
**local/no-auth HTTP smoke test** and cannot complete an interactive Cloudflare
Managed OAuth login; do not use it as proof that remote authorization works.

After Cloudflare Access login succeeds in ChatGPT's custom MCP app, connect
using `https://YOUR-HOSTNAME/mcp` and verify `get_capabilities` and read-only
X tools. If the login/connection fails, review the Access application policy,
Managed OAuth/redirect settings, tunnel route, Cloudflare logs and
`cloudflared` logs. Do not temporarily remove Access to diagnose it.

Cloudflare's MCP-specific Access application guidance calls for the origin to
validate `Cf-Access-Jwt-Assertion`; this project does **not** yet implement
that origin validation. Do not treat this edge-protected setup as equivalent
to end-to-end OAuth verification by the MCP server. If you require origin-side
token verification or enable X write operations, use a separately hardened
deployment before publishing those capabilities.

## 5. Stop or rotate

To stop only the tunnel sidecar while keeping the local MCP service:

```powershell
docker compose -f compose.private.yml -f compose.cloudflare.yml stop cloudflared
```

If the token leaks, rotate it in Cloudflare, update only the local `.env`,
and recreate the sidecar. Removing the tunnel route or disabling the Access
application does not replace token rotation.

Cloudflare references:
- [Create and route a Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/)
- [Cloudflare Access Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
- [Secure MCP servers](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/secure-mcp-servers/)
