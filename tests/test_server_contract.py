from typing import Any

import pytest
from mcp import Client

from agent_reach_mcp.config import Settings
from agent_reach_mcp.server import create_mcp


class FakeGateway:
    async def get_capabilities(self, refresh: bool = False) -> dict[str, Any]:
        return {"ok": True, "refresh": refresh}

    async def read_url(self, url: str, max_chars: int | None = None) -> dict[str, Any]:
        return {"url": url, "content": "test", "max_chars": max_chars}

    async def search_x(self, *args: Any) -> dict[str, Any]:
        return {"items": [], "args": list(args)}

    async def get_x_user_posts(self, *args: Any) -> dict[str, Any]:
        return {"items": [], "args": list(args)}

    async def get_x_post(self, *args: Any) -> dict[str, Any]:
        return {"items": [], "args": list(args)}

    async def get_youtube_transcript(self, *args: Any) -> dict[str, Any]:
        return {"content": "transcript", "args": list(args)}


@pytest.mark.asyncio
async def test_server_exposes_expected_tools() -> None:
    mcp = create_mcp(Settings(_env_file=None), gateway=FakeGateway())  # type: ignore[arg-type]
    async with Client(mcp) as client:
        page = await client.list_tools()
        names = {tool.name for tool in page.tools}
        assert names == {
            "get_capabilities",
            "read_url",
            "search_x",
            "get_x_user_posts",
            "get_x_post",
            "get_youtube_transcript",
        }
        result = await client.call_tool("read_url", {"url": "https://example.com"})
        assert not result.is_error
        assert result.structured_content == {"url": "https://example.com", "content": "test", "max_chars": None}
