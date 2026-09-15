import asyncio
import time
from typing import Any

from agent_reach.channels.web import WebChannel
from agent_reach.config import Config
from agent_reach.core import AgentReach
from agent_reach.utils.url import normalize_public_http_url

from .config import Settings
from .models import ReadUrlResult
from .twitter import TwitterAdapter
from .youtube import YoutubeAdapter

class Gateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._config = Config(read_only=True)
        self._agent_reach = AgentReach(self._config)
        self._web = WebChannel()
        self._twitter = TwitterAdapter(self._config, settings.request_timeout_seconds, settings.max_output_bytes)
        self._youtube = YoutubeAdapter(settings.max_text_chars, settings.max_output_bytes)
        self._capabilities_cache: tuple[float, dict[str, Any]] | None = None
        self._capabilities_lock = asyncio.Lock()

    async def get_capabilities(self, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not refresh and self._capabilities_cache and now - self._capabilities_cache[0] < self.settings.capabilities_cache_ttl_seconds:
            return self._capabilities_cache[1]
        async with self._capabilities_lock:
            now = time.monotonic()
            if not refresh and self._capabilities_cache and now - self._capabilities_cache[0] < self.settings.capabilities_cache_ttl_seconds:
                return self._capabilities_cache[1]
            report = await asyncio.to_thread(self._agent_reach.doctor_report)
            value = {"agent_reach": report, "mcp_tools": ["get_capabilities", "read_url", "search_x", "get_x_user_posts", "get_x_post", "get_youtube_transcript"]}
            self._capabilities_cache = (time.monotonic(), value)
            return value

    async def read_url(self, url: str, max_chars: int | None = None) -> dict[str, Any]:
        normalized = normalize_public_http_url(url)
        content = await asyncio.to_thread(self._web.read, normalized)
        limit = min(max_chars or self.settings.max_text_chars, self.settings.max_text_chars)
        if limit < 1000:
            raise ValueError("max_chars must be at least 1000")
        truncated = len(content) > limit
        if truncated:
            content = content[:limit]
        return ReadUrlResult(url=normalized, content=content, truncated=truncated, warnings=["Content was truncated."] if truncated else []).model_dump(mode="json")

    async def search_x(self, query: str, limit: int = 10, from_user: str | None = None, since: str | None = None, until: str | None = None) -> dict[str, Any]:
        return (await self._twitter.search(query, limit, from_user, since, until)).model_dump(mode="json")

    async def get_x_user_posts(self, username: str, limit: int = 20) -> dict[str, Any]:
        return (await self._twitter.user_posts(username, limit)).model_dump(mode="json")

    async def get_x_post(self, post: str) -> dict[str, Any]:
        return (await self._twitter.get_post(post)).model_dump(mode="json")

    async def get_youtube_transcript(self, url: str, languages: list[str] | None = None) -> dict[str, Any]:
        return (await self._youtube.transcript(url, languages)).model_dump(mode="json")
