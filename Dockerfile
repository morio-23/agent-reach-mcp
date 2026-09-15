FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

RUN useradd --system --create-home --uid 10001 appuser
USER appuser

ENV AGENT_REACH_MCP_TRANSPORT=streamable-http \
    AGENT_REACH_MCP_AUTH_MODE=none \
    AGENT_REACH_MCP_HOST=127.0.0.1 \
    AGENT_REACH_MCP_PORT=8080 \
    AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE=false

EXPOSE 8080

ENTRYPOINT ["agent-reach-mcp"]
