# Self-hosting

This guide prepares a persistent private `agent-reach-mcp` service listening only on loopback. It is suitable for a Linux host or WSL2 instance that will later be connected through a private MCP tunnel.

## 1. Install the project

Example layout:

```text
/opt/agent-reach-mcp
/etc/agent-reach-mcp.env
/var/lib/agent-reach-mcp
```

Create a dedicated service account and directories:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin agent-reach-mcp
sudo mkdir -p /opt/agent-reach-mcp /var/lib/agent-reach-mcp
sudo chown -R agent-reach-mcp:agent-reach-mcp /opt/agent-reach-mcp /var/lib/agent-reach-mcp
```

Clone the repository and create a virtual environment as the service account:

```bash
sudo -u agent-reach-mcp git clone https://github.com/morio-23/agent-reach-mcp.git /opt/agent-reach-mcp
sudo -u agent-reach-mcp python3 -m venv /opt/agent-reach-mcp/.venv
sudo -u agent-reach-mcp /opt/agent-reach-mcp/.venv/bin/pip install -U pip
sudo -u agent-reach-mcp /opt/agent-reach-mcp/.venv/bin/pip install -e /opt/agent-reach-mcp
```

Install the optional X backend if this host will expose the X MCP tools:

```bash
sudo -u agent-reach-mcp /opt/agent-reach-mcp/.venv/bin/pip install -e '/opt/agent-reach-mcp[x]'
```

While this repository remains private, use an authenticated Git checkout appropriate for your environment. Do not place a GitHub token in the systemd unit or tracked files.

## 2. Configure the service

Copy the example environment file:

```bash
sudo cp deploy/systemd/agent-reach-mcp.env.example /etc/agent-reach-mcp.env
sudo chown root:agent-reach-mcp /etc/agent-reach-mcp.env
sudo chmod 640 /etc/agent-reach-mcp.env
```

The private/tunnel configuration intentionally binds only to `127.0.0.1` and uses `AUTH_MODE=none`.

Agent Reach stores persistent configuration under the service user's `~/.agent-reach/` directory. If X is enabled, prefer Agent Reach's manual Cookie-Editor import flow under that service identity, or place the explicit `TWITTER_AUTH_TOKEN` / `TWITTER_CT0` values in the protected environment file. Never commit them.

## 3. Install systemd unit

```bash
sudo cp deploy/systemd/agent-reach-mcp.service /etc/systemd/system/agent-reach-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now agent-reach-mcp
```

Check status and logs:

```bash
systemctl status agent-reach-mcp
journalctl -u agent-reach-mcp -f
```

## 4. Verify locally

The endpoint should be reachable only from the host:

```bash
curl -i http://127.0.0.1:8080/mcp
```

A plain GET is not a complete MCP client test. Use the project verification script from the checkout:

```bash
cd /opt/agent-reach-mcp
.venv/bin/python scripts/http_verify.py
```

Expected behavior is successful MCP initialization, six tools, and a successful `get_capabilities` call.

## 5. Check backends

Run Agent Reach doctor with the same service identity/environment where practical:

```bash
sudo -u agent-reach-mcp /opt/agent-reach-mcp/.venv/bin/agent-reach doctor
```

For X, first verify the upstream CLI independently before testing through MCP.

For YouTube, verify `yt-dlp`/JS-runtime health according to Agent Reach doctor output.

## Docker / Compose alternative

The repository also includes a private Compose example:

```bash
docker compose -f compose.private.yml build
docker compose -f compose.private.yml up -d
python scripts/http_verify.py
```

It publishes only `127.0.0.1:8080` on the host. The application listens on `0.0.0.0` only inside the container so Docker can publish the port.

Agent Reach state is persisted in the `agent-reach-data` named volume at `/home/appuser/.agent-reach`. Configure X credentials interactively without baking them into the image:

```bash
docker compose -f compose.private.yml run --rm --entrypoint agent-reach \
  agent-reach-mcp configure twitter-cookies
```

Then restart the service:

```bash
docker compose -f compose.private.yml up -d
```

Do not copy `.agent-reach` state into the repository or Docker build context.

## WSL2 notes

Modern WSL2 distributions can use systemd when enabled in `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

After changing that setting, shut down and restart the WSL distribution. If you prefer not to use systemd, run `agent-reach-mcp` under another process supervisor, but keep the same loopback-only network and credential model.

## Public deployment

Do not change the private recipe to `0.0.0.0` with `AUTH_MODE=none` merely to make ChatGPT reach it.

For a public endpoint:

- terminate HTTPS at a reverse proxy/load balancer;
- configure `AUTH_MODE=oauth`;
- set `AGENT_REACH_MCP_PUBLIC_BASE_URL` to the external HTTPS origin;
- use a real OAuth/OIDC issuer with appropriate scopes and refresh-token/offline-access support;
- firewall the upstream application port where possible.

See [`chatgpt.md`](chatgpt.md) for the ChatGPT-specific connection model.
