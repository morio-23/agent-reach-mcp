import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from agent_reach.config import Config

from agent_reach_mcp.config import Settings
from agent_reach_mcp.errors import BackendExecutionError
from agent_reach_mcp.twitter import TwitterAdapter


@contextmanager
def running_server(tmp_path: Path, port: int):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AGENT_REACH_MCP_")
        and key not in {"TWITTER_AUTH_TOKEN", "TWITTER_CT0"}
    }
    env.update(
        HOME=str(tmp_path),
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
        PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""),
    )
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "agent_reach_mcp.server", "--transport",
             "streamable-http", "--port", str(port)],
            env=env,
            cwd=tmp_path,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                headers={"Accept": "application/json, text/event-stream"},
                timeout=10,
                trust_env=False,
            ) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(log.read())
                    try:
                        client.get("/")
                        break
                    except httpx.ConnectError:
                        time.sleep(0.1)
                else:
                    pytest.fail("MCP entrypoint did not start")
                yield client
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_http_without_sessions_survives_delete_and_restart(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    for _ in range(2):
        with running_server(tmp_path, port) as client:
            initialized = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "regression", "version": "1"}},
            })
            assert initialized.status_code == 200
            assert initialized.json()["result"]["serverInfo"]["name"] == "agent-reach-mcp"
            assert "mcp-session-id" not in initialized.headers
            for _ in range(2):
                response = client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list",
                })
                assert response.status_code == 200
                assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
                    "get_capabilities", "read_url", "search_x", "get_x_user_posts",
                    "get_x_post", "get_youtube_transcript",
                }
                assert client.delete("/mcp").status_code == 405
            result = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "search_x", "arguments": {"query": "OpenAI", "limit": 1}},
            }).json()["result"]
            assert result["isError"] is True
            message = result["content"][0]["text"]
            assert "twitter-cli: explicit Twitter credentials are required" in message
            assert "twifork: explicit Twitter credentials are required" in message


async def test_fallback_scrubs_primary_url_before_truncating(tmp_path: Path) -> None:
    if os.environ.get("TWITTER_AUTH_TOKEN") and os.environ.get("TWITTER_CT0"):
        pytest.skip("requires absent X credentials")
    settings = Settings(_env_file=None)
    adapter = TwitterAdapter(
        Config(tmp_path / "absent.yml", read_only=True),
        settings.request_timeout_seconds,
        settings.max_output_bytes,
    )
    with pytest.raises(BackendExecutionError) as caught:
        await adapter._fallback(
            BackendExecutionError("https://example-user:" + "s" * 500 + "@example.test/failure"),
            lambda: adapter._twifork_search("OpenAI", 1, None, None, None),
        )
    message = str(caught.value)
    assert "twitter-cli: https://***@example.test/failure" in message
    assert "twifork: explicit Twitter credentials are required" in message
    assert "example-user" not in message
    assert "s" * 20 not in message
