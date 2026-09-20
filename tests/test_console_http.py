import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent_reach_mcp.console import ConsoleServer, ConsoleStore


class FakeGateway:
    async def get_x_user_posts(self, username: str, limit: int):
        return {
            "source": {"backend": "twitter-cli"},
            "warnings": [],
            "items": [{"id": "1234567890", "author": {"username": username},
                       "content": "event announcement",
                       "url": f"https://x.com/{username}/status/1234567890"}][:limit],
        }

    async def read_url(self, url: str):
        return {"url": url, "content": "Web research example",
                "source": {"platform": "web", "backend": "fake-reader"}}

    async def search_x(self, query: str, limit: int):
        return {"source": {"backend": "twifork"}, "warnings": ["fallback"],
                "items": [{"id": "9876543210", "author": {"username": "source"},
                           "content": query}][:limit]}


@pytest.fixture
def live_console(tmp_path: Path):
    server = ConsoleServer(("127.0.0.1", 0), "a" * 64,
                           ConsoleStore(tmp_path / "console.sqlite3"),
                           FakeGateway())  # type: ignore[arg-type]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        yield origin
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(origin: str, path: str, payload=None, *, authorized=True, valid_origin=True):
    headers = {"Host": origin.split("://")[1]}
    if authorized:
        headers["X-Console-Token"] = "a" * 64
    if payload is not None:
        headers["Content-Type"] = "application/json"
        if valid_origin:
            headers["Origin"] = origin
    body = json.dumps(payload).encode() if payload is not None else None
    return urlopen(Request(origin + path, headers=headers, data=body), timeout=5)


def test_console_requires_auth_and_same_origin(live_console: str) -> None:
    with pytest.raises(HTTPError) as unauthenticated:
        request(live_console, "/api/sources", authorized=False)
    assert unauthenticated.value.code == 401
    with pytest.raises(HTTPError) as cross_origin:
        request(live_console, "/api/sources", {"kind": "user", "value": "LoveLive_staff"},
                valid_origin=False)
    assert cross_origin.value.code == 403
    with pytest.raises(HTTPError) as unknown_endpoint:
        request(live_console, "/api/post_x", {"text": "should not post"})
    assert unknown_endpoint.value.code == 404


def test_console_research_and_review_endpoints(live_console: str) -> None:
    with request(live_console, "/api/sources",
                 {"kind": "user", "value": "LoveLive_staff"}) as response:
        source_id = json.load(response)["source"]["id"]
    with request(live_console, "/api/research",
                 {"source_id": source_id, "limit": 3}) as response:
        research = json.load(response)
    assert research["new"] == 1
    assert research["backend"] == "twitter-cli"
    with request(live_console, "/api/research",
                 {"source_id": source_id, "limit": 3}) as response:
        assert json.load(response)["new"] == 0
    with request(live_console, "/api/findings/review",
                 {"post_id": "1234567890", "category": "event",
                  "state": "reviewed", "notes": "needs review"}) as response:
        assert json.load(response) == {"ok": True}
    with request(live_console, "/api/findings") as response:
        result = json.load(response)["findings"]
    assert len(result) == 1
    assert result[0]["category"] == "event"
    assert result[0]["notes"] == "needs review"


def test_platform_neutral_web_research_and_review(live_console: str) -> None:
    with request(live_console, "/api/sources",
                 {"kind": "web", "value": "https://example.com/news",
                  "label": "News"}) as response:
        source = json.load(response)["source"]
    assert source["label"] == "News"
    with request(live_console, "/api/research",
                 {"source_id": source["id"], "limit": 1}) as response:
        assert json.load(response)["new"] == 1
    with request(live_console, "/api/items") as response:
        items = json.load(response)["items"]
    assert len(items) == 1
    assert items[0]["platform"] == "web"
    item_id = items[0]["item_id"]
    with request(live_console, "/api/items/review",
                 {"item_id": item_id, "state": "reviewed", "notes": "Saved",
                  "tags": ["news"], "collections": ["General research"]}) as response:
        assert json.load(response)["ok"] is True
    with request(live_console, "/api/items?state=reviewed&collection=General%20research") as response:
        reviewed = json.load(response)["items"]
    assert len(reviewed) == 1
    assert reviewed[0]["tags"] == ["news"]
    assert reviewed[0]["collections"] == ["General research"]
    with request(live_console, "/api/collections") as response:
        assert json.load(response)["collections"] == ["General research"]
