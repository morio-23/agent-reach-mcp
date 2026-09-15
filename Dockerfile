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

# Streamable HTTP is the useful container transport. Binding to 0.0.0.0 is
# required for Docker port publishing, but unauthenticated remote listening is
# still rejected by the application unless the operator explicitly configures
# OAuth/static-token auth or opts into an insecure/private-container boundary.
ENV AGENT_REACH_MCP_TRANSPORT=streamable-http \
    AGENT_REACH_MCP_HOST=0.0.0.0 \
    AGENT_REACH_MCP_PORT=8080

EXPOSE 8080

ENTRYPOINT ["agent-reach-mcp"]
