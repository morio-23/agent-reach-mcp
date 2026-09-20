import json
from pathlib import Path

import pytest

from agent_reach_mcp.console import ConsoleStore


def test_register_sources_and_validate_input(tmp_path: Path) -> None:
    store = ConsoleStore(tmp_path / "state" / "console.sqlite3")
    first = store.add_source("user", "@LoveLive_staff")
    same = store.add_source("user", "LoveLive_staff")
    query = store.add_source("query", "ラブライブ 発売")
    assert first["id"] == same["id"]
    assert query["kind"] == "query"
    assert len(store.sources()) == 2
    with pytest.raises(ValueError):
        store.add_source("user", "bad username;")
    with pytest.raises(ValueError):
        store.add_source("query", "")
    store.remove_source(first["id"])
    assert len(store.sources()) == 1


def test_findings_are_deduplicated_and_review_is_persistent(tmp_path: Path) -> None:
    path = tmp_path / "console.sqlite3"
    store = ConsoleStore(path)
    result = {
        "source": {"platform": "x", "backend": "twifork"},
        "warnings": ["fallback"],
        "items": [
            {
                "id": "2101687621298933804",
                "author": {"username": "LoveLive_staff"},
                "content": "New event announced",
                "url": "https://x.com/LoveLive_staff/status/2101687621298933804",
                "published_at": "2026-09-20T14:39:17+00:00",
            },
            {"id": "not-a-post", "content": "not a valid post"},
        ],
    }
    assert store.save_findings(result) == {
        "fetched": 2,
        "new": 1,
        "backend": "twifork",
        "warnings": ["fallback"],
    }
    assert store.save_findings(result)["new"] == 0
    store.review("2101687621298933804", "event", "reviewed", "Needs calendar check")
    rows = ConsoleStore(path).findings()
    assert len(rows) == 1
    assert rows[0]["category"] == "event"
    assert rows[0]["state"] == "reviewed"
    assert rows[0]["notes"] == "Needs calendar check"
    with pytest.raises(ValueError):
        store.review("2101687621298933804", "invalid", "reviewed", "")
    with pytest.raises(ValueError):
        store.review("1", "event", "approved", "")


def test_console_source_values_are_not_executable(tmp_path: Path) -> None:
    store = ConsoleStore(tmp_path / "console.sqlite3")
    with pytest.raises(ValueError):
        store.add_source("user", "../../etc/passwd")
    with pytest.raises(ValueError):
        store.add_source("query", "x" * 201)
    assert json.dumps(store.sources()) == "[]"


def test_console_gateway_settings_ignore_docker_http_listener_defaults(monkeypatch):
    """Docker image's public MCP defaults must not block the local console."""
    from agent_reach_mcp.config import Settings, TransportMode

    monkeypatch.setenv("AGENT_REACH_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("AGENT_REACH_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENT_REACH_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("AGENT_REACH_MCP_ALLOW_INSECURE_REMOTE", raising=False)
    settings = Settings(
        _env_file=None,  # Isolate from the developer local dotenv.
        transport=TransportMode.STDIO, host="127.0.0.1", x_write_enabled=False
    )
    assert settings.transport is TransportMode.STDIO
    assert settings.host == "127.0.0.1"
    assert settings.x_write_enabled is False
