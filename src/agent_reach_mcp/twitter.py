import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import date
from typing import Any
from urllib.parse import urlparse

from agent_reach.channels.twitter import twitter_cli_child_env
from agent_reach.config import Config

from .errors import BackendExecutionError, BackendUnavailableError
from .models import AuthorInfo, ContentItem, ItemResult, SourceInfo

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TWEET_ID_RE = re.compile(r"^\d{1,30}$")

class TwitterAdapter:
    def __init__(self, config: Config, timeout_seconds: float, max_output_bytes: int):
        self._config = config
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes

    async def search(self, query: str, limit: int, from_user: str | None = None, since: str | None = None, until: str | None = None) -> ItemResult:
        return await asyncio.to_thread(self._search_sync, query, limit, from_user, since, until)

    async def user_posts(self, username: str, limit: int) -> ItemResult:
        return await asyncio.to_thread(self._user_posts_sync, username, limit)

    async def get_post(self, post: str) -> ItemResult:
        return await asyncio.to_thread(self._get_post_sync, post)

    def _search_sync(self, query: str, limit: int, from_user: str | None, since: str | None, until: str | None) -> ItemResult:
        query = query.strip()
        if not query or len(query) > 512:
            raise ValueError("query must contain 1 to 512 characters")
        args = ["search", query, "--max", str(_validate_limit(limit)), "--json"]
        if from_user:
            args += ["--from", _validate_username(from_user)]
        if since:
            args += ["--since", _validate_date(since)]
        if until:
            args += ["--until", _validate_date(until)]
        return _to_result(self._run(args))

    def _user_posts_sync(self, username: str, limit: int) -> ItemResult:
        return _to_result(self._run(["user-posts", _validate_username(username), "--max", str(_validate_limit(limit)), "--json"]))

    def _get_post_sync(self, post: str) -> ItemResult:
        return _to_result(self._run(["tweet", _validate_post_ref(post), "--json"]))

    def _run(self, args: list[str]) -> dict[str, Any]:
        executable = shutil.which("twitter")
        if not executable:
            raise BackendUnavailableError("twitter-cli is not installed")
        env = os.environ.copy()
        env.update(twitter_cli_child_env(self._config))
        env.update({"OUTPUT": "json", "NO_COLOR": "1", "PYTHONUTF8": "1"})
        try:
            cp = subprocess.run([executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self._timeout, env=env, shell=False, check=False)
        except subprocess.TimeoutExpired as exc:
            raise BackendExecutionError(f"twitter-cli timed out after {self._timeout:g} seconds") from exc
        stdout = cp.stdout or ""
        if len(stdout.encode("utf-8")) > self._max_output:
            raise BackendExecutionError("twitter-cli output exceeded the configured size limit")
        payload = None
        if stdout.strip():
            try:
                candidate = json.loads(stdout)
                if isinstance(candidate, dict):
                    payload = candidate
            except json.JSONDecodeError:
                pass
        if payload and payload.get("ok") is False:
            error = payload.get("error") or {}
            raise BackendExecutionError(f"twitter-cli {error.get('code') or 'backend_error'}: {error.get('message') or 'request failed'}")
        if cp.returncode != 0:
            msg = (cp.stderr or "twitter-cli request failed").strip().splitlines()[-1]
            raise BackendExecutionError(msg[:500])
        if payload is None or payload.get("ok") is not True:
            raise BackendExecutionError("twitter-cli returned an invalid structured response")
        return payload

def _to_result(payload: dict[str, Any]) -> ItemResult:
    data = payload.get("data")
    rows = [data] if isinstance(data, dict) else [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    warnings = ["Additional results are available."] if isinstance(payload.get("pagination"), dict) and payload["pagination"].get("nextCursor") else []
    return ItemResult(items=[_normalize_tweet(x) for x in rows], source=SourceInfo(platform="x", backend="twitter-cli"), warnings=warnings)

def _normalize_tweet(raw: dict[str, Any]) -> ContentItem:
    author_raw = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    username = author_raw.get("screenName") or author_raw.get("username")
    tweet_id = str(raw.get("id")) if raw.get("id") is not None else None
    return ContentItem(
        id=tweet_id, platform="x", type="post", content=str(raw.get("text") or ""),
        url=f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else None,
        title=raw.get("articleTitle"),
        author=AuthorInfo(id=str(author_raw.get("id")) if author_raw.get("id") is not None else None, username=str(username) if username else None, display_name=str(author_raw.get("name")) if author_raw.get("name") else None),
        published_at=raw.get("createdAtISO") or raw.get("createdAt"),
        metadata={"metrics": raw.get("metrics") or {}, "lang": raw.get("lang"), "media": raw.get("media") or [], "urls": raw.get("urls") or [], "is_retweet": bool(raw.get("isRetweet", False))},
    )

def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return limit

def _validate_username(username: str) -> str:
    value = username.strip().lstrip("@")
    if not _USERNAME_RE.fullmatch(value):
        raise ValueError("username must be a valid X handle")
    return value

def _validate_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("date filters must use YYYY-MM-DD") from exc

def _validate_post_ref(value: str) -> str:
    value = value.strip()
    if _TWEET_ID_RE.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        raise ValueError("post must be a numeric ID or HTTPS X status URL")
    parts = [x for x in parsed.path.split("/") if x]
    if len(parts) < 3 or parts[-2] != "status" or not _TWEET_ID_RE.fullmatch(parts[-1]):
        raise ValueError("post URL must point to an X status")
    return value
