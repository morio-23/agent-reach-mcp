import asyncio
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

from agent_reach.channels.twitter import twitter_cli_child_env
from agent_reach.config import Config
from agent_reach.utils.url import normalize_public_http_url

from .errors import BackendExecutionError, BackendUnavailableError
from .models import AuthorInfo, ContentItem, ItemResult, SourceInfo

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TWEET_ID_RE = re.compile(r"^\d{1,30}$")
_MAX_IMAGE_COUNT = 4
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_ALT_TEXT_CHARS = 1000
_MAX_REDIRECTS = 3


@dataclass(frozen=True)
class _ImageUpload:
    data: bytes
    media_type: str
    alt_text: str | None = None


class TwitterAdapter:
    def __init__(
        self,
        config: Config,
        timeout_seconds: float,
        max_output_bytes: int,
        twifork_fallback_enabled: bool = True,
        write_enabled: bool = False,
    ):
        self._config = config
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._twifork_fallback_enabled = twifork_fallback_enabled
        self._write_enabled = write_enabled

    async def search(
        self,
        query: str,
        limit: int,
        from_user: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> ItemResult:
        query = query.strip()
        if not query or len(query) > 512:
            raise ValueError("query must contain 1 to 512 characters")
        limit = _validate_limit(limit)
        if from_user:
            from_user = _validate_username(from_user)
        if since:
            since = _validate_date(since)
        if until:
            until = _validate_date(until)
        try:
            return await asyncio.to_thread(
                self._search_sync, query, limit, from_user, since, until
            )
        except (BackendUnavailableError, BackendExecutionError) as primary_error:
            return await self._fallback(
                primary_error,
                lambda: self._twifork_search(query, limit, from_user, since, until),
            )

    async def user_posts(self, username: str, limit: int) -> ItemResult:
        username = _validate_username(username)
        limit = _validate_limit(limit)
        try:
            return await asyncio.to_thread(self._user_posts_sync, username, limit)
        except (BackendUnavailableError, BackendExecutionError) as primary_error:
            return await self._fallback(
                primary_error,
                lambda: self._twifork_user_posts(username, limit),
            )

    async def get_post(self, post: str) -> ItemResult:
        post_ref = _validate_post_ref(post)
        try:
            return await asyncio.to_thread(self._get_post_sync, post_ref)
        except (BackendUnavailableError, BackendExecutionError) as primary_error:
            return await self._fallback(
                primary_error,
                lambda: self._twifork_get_post(_tweet_id_from_ref(post_ref)),
            )

    async def post(
        self,
        text: str,
        confirm: bool = False,
        reply_to: str | None = None,
        media_urls: list[str] | None = None,
        media_alt_texts: list[str] | None = None,
    ) -> ItemResult:
        if not self._write_enabled:
            raise BackendUnavailableError(
                "X write operations are disabled; set AGENT_REACH_MCP_X_WRITE_ENABLED=true to expose posting"
            )
        if confirm is not True:
            raise ValueError("confirm=true is required for X write operations")
        text = text.strip()
        if not text or len(text) > 280:
            raise ValueError("text must contain 1 to 280 characters")
        reply_id = (
            _tweet_id_from_ref(_validate_post_ref(reply_to)) if reply_to else None
        )
        urls, alt_texts = _validate_media_inputs(media_urls, media_alt_texts)
        uploads: list[_ImageUpload] = []
        if urls:
            downloaded = await asyncio.gather(
                *(asyncio.to_thread(_download_public_image, url) for url in urls)
            )
            uploads = [
                _ImageUpload(data=data, media_type=media_type, alt_text=alt_texts[index])
                for index, (data, media_type) in enumerate(downloaded)
            ]
        return await self._run_twifork(
            "post",
            lambda client: _create_tweet_with_media(client, text, reply_id, uploads),
            normalizer=lambda tweet: _twifork_result([tweet], write=True),
        )

    async def _fallback(
        self,
        primary_error: Exception,
        fallback: Callable[[], Awaitable[ItemResult]],
    ) -> ItemResult:
        if not self._twifork_fallback_enabled:
            raise primary_error
        try:
            result = await fallback()
        except (BackendUnavailableError, BackendExecutionError) as fallback_error:
            raise BackendExecutionError(
                "twitter-cli failed and twifork fallback also failed: "
                f"{type(fallback_error).__name__}: {str(fallback_error)[:300]}"
            ) from None
        result.warnings.insert(
            0,
            "Primary twitter-cli backend failed; served by twifork fallback.",
        )
        return result

    def _search_sync(
        self,
        query: str,
        limit: int,
        from_user: str | None,
        since: str | None,
        until: str | None,
    ) -> ItemResult:
        args = ["search", query, "--max", str(limit), "--json"]
        if from_user:
            args += ["--from", from_user]
        if since:
            args += ["--since", since]
        if until:
            args += ["--until", until]
        return _to_result(self._run(args))

    def _user_posts_sync(self, username: str, limit: int) -> ItemResult:
        return _to_result(
            self._run(["user-posts", username, "--max", str(limit), "--json"])
        )

    def _get_post_sync(self, post: str) -> ItemResult:
        tweet_id = _tweet_id_from_ref(post)
        return _to_single_result(
            self._run(["tweet", post, "--json"]), expected_id=tweet_id
        )

    def _run(self, args: list[str]) -> dict[str, Any]:
        executable = shutil.which("twitter")
        if not executable:
            raise BackendUnavailableError("twitter-cli is not installed")
        env = os.environ.copy()
        env.update(twitter_cli_child_env(self._config))
        if not env.get("TWITTER_AUTH_TOKEN") or not env.get("TWITTER_CT0"):
            raise BackendUnavailableError(
                "explicit Twitter credentials are required; configure TWITTER_AUTH_TOKEN and TWITTER_CT0 through Agent Reach before using X tools"
            )
        env.update({"OUTPUT": "json", "NO_COLOR": "1", "PYTHONUTF8": "1"})
        try:
            cp = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendExecutionError(
                f"twitter-cli timed out after {self._timeout:g} seconds"
            ) from exc
        stdout = cp.stdout or ""
        if len(stdout.encode("utf-8")) > self._max_output:
            raise BackendExecutionError(
                "twitter-cli output exceeded the configured size limit"
            )
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
            raise BackendExecutionError(
                f"twitter-cli {error.get('code') or 'backend_error'}: "
                f"{error.get('message') or 'request failed'}"
            )
        if cp.returncode != 0:
            msg = (cp.stderr or "twitter-cli request failed").strip().splitlines()[-1]
            raise BackendExecutionError(msg[:500])
        if payload is None or payload.get("ok") is not True:
            raise BackendExecutionError(
                "twitter-cli returned an invalid structured response"
            )
        return payload

    async def _twifork_search(
        self,
        query: str,
        limit: int,
        from_user: str | None,
        since: str | None,
        until: str | None,
    ) -> ItemResult:
        parts = [query]
        if from_user:
            parts.append(f"from:{from_user}")
        if since:
            parts.append(f"since:{since}")
        if until:
            parts.append(f"until:{until}")
        search_query = " ".join(parts)

        async def operation(client: Any) -> tuple[list[Any], bool]:
            page = await client.search_tweet(
                search_query, "Latest", count=min(limit, 20)
            )
            return await _collect_twifork_pages(page, limit)

        return await self._run_twifork(
            "search",
            operation,
            normalizer=lambda value: _twifork_result(value[0], has_more=value[1]),
        )

    async def _twifork_user_posts(self, username: str, limit: int) -> ItemResult:
        async def operation(client: Any) -> tuple[list[Any], bool]:
            user = await client.get_user_by_screen_name(username)
            page = await client.get_user_tweets(
                user.id, "Tweets", count=min(limit, 40)
            )
            return await _collect_twifork_pages(page, limit)

        return await self._run_twifork(
            "user-posts",
            operation,
            normalizer=lambda value: _twifork_result(value[0], has_more=value[1]),
        )

    async def _twifork_get_post(self, tweet_id: str) -> ItemResult:
        return await self._run_twifork(
            "tweet",
            lambda client: client.get_tweet_by_id(tweet_id),
            normalizer=lambda tweet: _twifork_result([tweet]),
        )

    async def _run_twifork(
        self,
        operation_name: str,
        operation: Callable[[Any], Awaitable[Any]],
        normalizer: Callable[[Any], ItemResult],
    ) -> ItemResult:
        try:
            from twikit import Client
        except ImportError as exc:
            raise BackendUnavailableError(
                "twifork is not installed; install the x extra"
            ) from exc

        env = os.environ.copy()
        env.update(twitter_cli_child_env(self._config))
        auth_token = env.get("TWITTER_AUTH_TOKEN")
        ct0 = env.get("TWITTER_CT0")
        if not auth_token or not ct0:
            raise BackendUnavailableError(
                "explicit Twitter credentials are required; configure TWITTER_AUTH_TOKEN and TWITTER_CT0 through Agent Reach before using X tools"
            )

        try:
            client = Client("en-US", impersonate="chrome124")
            client.set_cookies({"auth_token": auth_token, "ct0": ct0})
            value = await asyncio.wait_for(operation(client), timeout=self._timeout)
            return normalizer(value)
        except asyncio.TimeoutError as exc:
            raise BackendExecutionError(
                f"twifork {operation_name} timed out after {self._timeout:g} seconds"
            ) from exc
        except (BackendUnavailableError, BackendExecutionError):
            raise
        except Exception as exc:
            message = str(exc).strip() or "request failed"
            raise BackendExecutionError(
                f"twifork {operation_name} failed: {message[:500]}"
            ) from exc


async def _create_tweet_with_media(
    client: Any,
    text: str,
    reply_id: str | None,
    uploads: list[_ImageUpload],
) -> Any:
    media_ids: list[str] = []
    for upload in uploads:
        media_id = await client.upload_media(
            upload.data,
            media_type=upload.media_type,
        )
        if upload.alt_text:
            await client.create_media_metadata(media_id, alt_text=upload.alt_text)
        media_ids.append(media_id)
    return await client.create_tweet(
        text=text,
        media_ids=media_ids or None,
        reply_to=reply_id,
    )


def _validate_media_inputs(
    media_urls: list[str] | None,
    media_alt_texts: list[str] | None,
) -> tuple[list[str], list[str | None]]:
    urls = list(media_urls or [])
    if len(urls) > _MAX_IMAGE_COUNT:
        raise ValueError(f"media_urls supports at most {_MAX_IMAGE_COUNT} images")
    normalized_urls = [_validate_public_image_url(url) for url in urls]

    if media_alt_texts is None:
        return normalized_urls, [None] * len(normalized_urls)

    alt_texts = list(media_alt_texts)
    if len(alt_texts) != len(normalized_urls):
        raise ValueError("media_alt_texts must have the same length as media_urls")
    normalized_alt_texts: list[str | None] = []
    for alt_text in alt_texts:
        value = alt_text.strip()
        if len(value) > _MAX_ALT_TEXT_CHARS:
            raise ValueError(
                f"media alt text must be at most {_MAX_ALT_TEXT_CHARS} characters"
            )
        normalized_alt_texts.append(value or None)
    return normalized_urls, normalized_alt_texts


def _validate_public_image_url(url: str) -> str:
    normalized = normalize_public_http_url(url)
    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https":
        raise ValueError("media URLs must use HTTPS")
    return normalized


def _download_public_image(url: str) -> tuple[bytes, str]:
    current = _validate_public_image_url(url)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for redirect_count in range(_MAX_REDIRECTS + 1):
        _assert_public_dns(current)
        request = urllib.request.Request(
            current,
            headers={
                "Accept": "image/webp,image/png,image/jpeg,*/*;q=0.1",
                "User-Agent": "agent-reach-mcp/0.1",
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                declared_length = response.headers.get("Content-Length")
                declared_size: int | None = None
                if declared_length:
                    try:
                        declared_size = int(declared_length)
                    except ValueError:
                        declared_size = None
                if declared_size is not None and declared_size > _MAX_IMAGE_BYTES:
                    raise ValueError(f"image exceeds {_MAX_IMAGE_BYTES} byte limit")
                data = response.read(_MAX_IMAGE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise BackendExecutionError(
                        "image download redirect did not include a Location header"
                    ) from None
                if redirect_count >= _MAX_REDIRECTS:
                    raise BackendExecutionError(
                        "image download exceeded redirect limit"
                    ) from None
                current = _validate_public_image_url(urljoin(current, location))
                continue
            raise BackendExecutionError(
                f"image download failed with HTTP {exc.code}"
            ) from None
        except OSError:
            raise BackendExecutionError("image download failed") from None

        if len(data) > _MAX_IMAGE_BYTES:
            raise ValueError(f"image exceeds {_MAX_IMAGE_BYTES} byte limit")
        media_type = _detect_image_mime(data)
        return data, media_type

    raise BackendExecutionError("image download exceeded redirect limit")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _assert_public_dns(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("media URL must include a hostname")
    try:
        addresses = socket.getaddrinfo(
            host,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise BackendExecutionError(
            f"image hostname could not be resolved: {host}"
        ) from exc
    if not addresses:
        raise BackendExecutionError(f"image hostname could not be resolved: {host}")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("media URL must resolve only to public IP addresses")


def _detect_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("media must be a PNG, JPEG, or WebP image")


async def _collect_twifork_pages(page: Any, limit: int) -> tuple[list[Any], bool]:
    items: list[Any] = []
    current = page
    has_more = False
    while current and len(items) < limit:
        page_items = list(current)
        remaining = limit - len(items)
        items.extend(page_items[:remaining])
        if len(page_items) > remaining:
            has_more = True
            break
        if len(items) >= limit:
            has_more = bool(getattr(current, "next_cursor", None))
            break
        next_page = await current.next()
        if not next_page:
            break
        current = next_page
    return items, has_more


def _to_result(payload: dict[str, Any]) -> ItemResult:
    data = payload.get("data")
    rows = (
        [data]
        if isinstance(data, dict)
        else [x for x in data if isinstance(x, dict)]
        if isinstance(data, list)
        else []
    )
    warnings = (
        ["Additional results are available."]
        if isinstance(payload.get("pagination"), dict)
        and payload["pagination"].get("nextCursor")
        else []
    )
    return ItemResult(
        items=[_normalize_tweet(x) for x in rows],
        source=SourceInfo(platform="x", backend="twitter-cli"),
        warnings=warnings,
    )


def _to_single_result(payload: dict[str, Any], expected_id: str) -> ItemResult:
    data = payload.get("data")
    rows = (
        [data]
        if isinstance(data, dict)
        else [x for x in data if isinstance(x, dict)]
        if isinstance(data, list)
        else []
    )
    match = next((row for row in rows if str(row.get("id")) == expected_id), None)
    if match is None:
        raise BackendExecutionError(
            "twitter-cli response did not contain the requested post"
        )
    return _to_result({**payload, "data": match})


def _twifork_result(
    tweets: list[Any], has_more: bool = False, write: bool = False
) -> ItemResult:
    warnings = []
    if has_more:
        warnings.append("Additional results are available.")
    if write:
        warnings.append(
            "Post was created through Twifork's unofficial X web-client API."
        )
    return ItemResult(
        items=[_normalize_twifork_tweet(tweet) for tweet in tweets],
        source=SourceInfo(platform="x", backend="twifork"),
        warnings=warnings,
    )


def _normalize_tweet(raw: dict[str, Any]) -> ContentItem:
    author_raw = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    username = author_raw.get("screenName") or author_raw.get("username")
    tweet_id = str(raw.get("id")) if raw.get("id") is not None else None
    return ContentItem(
        id=tweet_id,
        platform="x",
        type="post",
        content=str(raw.get("text") or ""),
        url=(
            f"https://x.com/{username}/status/{tweet_id}"
            if username and tweet_id
            else None
        ),
        title=raw.get("articleTitle"),
        author=AuthorInfo(
            id=(
                str(author_raw.get("id"))
                if author_raw.get("id") is not None
                else None
            ),
            username=str(username) if username else None,
            display_name=(
                str(author_raw.get("name")) if author_raw.get("name") else None
            ),
        ),
        published_at=raw.get("createdAtISO") or raw.get("createdAt"),
        metadata={
            "metrics": raw.get("metrics") or {},
            "lang": raw.get("lang"),
            "media": raw.get("media") or [],
            "urls": raw.get("urls") or [],
            "is_retweet": bool(raw.get("isRetweet", False)),
        },
    )


def _normalize_twifork_tweet(tweet: Any) -> ContentItem:
    user = getattr(tweet, "user", None)
    tweet_id_raw = getattr(tweet, "id", None)
    tweet_id = str(tweet_id_raw) if tweet_id_raw is not None else None
    username = (
        getattr(user, "screen_name", None)
        or getattr(user, "username", None)
        if user is not None
        else None
    )
    author_id_raw = getattr(user, "id", None) if user is not None else None
    created_at_raw = getattr(tweet, "created_at", None)
    published_at = str(created_at_raw) if created_at_raw is not None else None
    metrics = {
        key: value
        for key, value in {
            "likes": getattr(tweet, "favorite_count", None),
            "retweets": getattr(tweet, "retweet_count", None),
            "replies": getattr(tweet, "reply_count", None),
            "quotes": getattr(tweet, "quote_count", None),
            "views": getattr(tweet, "view_count", None),
        }.items()
        if value is not None
    }
    return ContentItem(
        id=tweet_id,
        platform="x",
        type="post",
        content=str(getattr(tweet, "text", "") or ""),
        url=(
            f"https://x.com/{username}/status/{tweet_id}"
            if username and tweet_id
            else None
        ),
        author=AuthorInfo(
            id=str(author_id_raw) if author_id_raw is not None else None,
            username=str(username) if username else None,
            display_name=(
                str(getattr(user, "name", ""))
                if user is not None and getattr(user, "name", None)
                else None
            ),
        ),
        published_at=published_at,
        metadata={
            "metrics": metrics,
            "lang": getattr(tweet, "lang", None),
            "is_retweet": bool(getattr(tweet, "retweeted_tweet", None)),
        },
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
    if parsed.scheme != "https" or parsed.hostname not in {
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
    }:
        raise ValueError("post must be a numeric ID or HTTPS X status URL")
    parts = [x for x in parsed.path.split("/") if x]
    if (
        len(parts) < 3
        or parts[-2] != "status"
        or not _TWEET_ID_RE.fullmatch(parts[-1])
    ):
        raise ValueError("post URL must point to an X status")
    return value


def _tweet_id_from_ref(value: str) -> str:
    if _TWEET_ID_RE.fullmatch(value):
        return value
    return urlparse(value).path.rstrip("/").split("/")[-1]
