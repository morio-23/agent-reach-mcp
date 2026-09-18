import socket
from types import SimpleNamespace

import pytest

import agent_reach_mcp.twitter as twitter_module
from agent_reach_mcp.errors import BackendExecutionError
from agent_reach_mcp.twitter import (
    TwitterAdapter,
    _assert_public_dns,
    _collect_twifork_pages,
    _create_tweet_with_media,
    _detect_image_mime,
    _download_public_image,
    _ImageUpload,
    _normalize_tweet,
    _normalize_twifork_tweet,
    _to_single_result,
    _tweet_id_from_ref,
    _validate_media_inputs,
    _validate_post_ref,
    _validate_public_image_url,
    _validate_username,
)


def test_normalize_tweet() -> None:
    item = _normalize_tweet(
        {
            "id": "123",
            "text": "hello",
            "createdAtISO": "2026-09-15T00:00:00Z",
            "author": {
                "id": "u1",
                "screenName": "example",
                "name": "Example",
            },
            "metrics": {"likes": 3},
        }
    )
    assert item.url == "https://x.com/example/status/123"
    assert item.author is not None
    assert item.author.username == "example"
    assert item.metadata["metrics"]["likes"] == 3


def test_normalize_twifork_tweet() -> None:
    tweet = SimpleNamespace(
        id="456",
        text="fallback",
        created_at="2026-09-18T00:00:00Z",
        favorite_count=7,
        retweet_count=2,
        reply_count=1,
        quote_count=0,
        view_count=99,
        lang="ja",
        retweeted_tweet=None,
        user=SimpleNamespace(id="u2", screen_name="example2", name="Example 2"),
    )
    item = _normalize_twifork_tweet(tweet)
    assert item.url == "https://x.com/example2/status/456"
    assert item.author is not None
    assert item.author.username == "example2"
    assert item.metadata["metrics"]["views"] == 99


def test_to_single_result_selects_requested_post() -> None:
    result = _to_single_result(
        {
            "ok": True,
            "data": [
                {"id": "123", "text": "requested"},
                {"id": "456", "text": "related"},
            ],
        },
        expected_id="123",
    )
    assert [item.id for item in result.items] == ["123"]


class FakeTwiforkClient:
    def __init__(self) -> None:
        self.uploads: list[tuple[bytes, str]] = []
        self.metadata: list[tuple[str, str]] = []
        self.created: dict[str, object] | None = None

    async def upload_media(self, data: bytes, media_type: str) -> str:
        self.uploads.append((data, media_type))
        return f"media-{len(self.uploads)}"

    async def create_media_metadata(self, media_id: str, alt_text: str) -> None:
        self.metadata.append((media_id, alt_text))

    async def create_tweet(
        self,
        text: str,
        media_ids: list[str] | None,
        reply_to: str | None,
    ) -> SimpleNamespace:
        self.created = {
            "text": text,
            "media_ids": media_ids,
            "reply_to": reply_to,
        }
        return SimpleNamespace(id="789", text=text, user=None)


@pytest.mark.asyncio
async def test_post_requires_confirmation_before_fetching_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = TwitterAdapter(
        SimpleNamespace(),
        timeout_seconds=1,
        max_output_bytes=1024,
        write_enabled=True,
    )

    def fail_if_called(url: str) -> tuple[bytes, str]:
        raise AssertionError(f"media fetch should not run: {url}")

    monkeypatch.setattr(twitter_module, "_download_public_image", fail_if_called)
    with pytest.raises(ValueError, match="confirm=true"):
        await adapter.post(
            "hello",
            confirm=False,
            media_urls=["https://images.example.com/one.png"],
        )


@pytest.mark.asyncio
async def test_create_tweet_with_media_uploads_images_and_alt_text() -> None:
    client = FakeTwiforkClient()
    tweet = await _create_tweet_with_media(
        client,
        "hello",
        "123",
        [
            _ImageUpload(b"png", "image/png", "first image"),
            _ImageUpload(b"jpg", "image/jpeg", None),
        ],
    )
    assert tweet.id == "789"
    assert client.uploads == [
        (b"png", "image/png"),
        (b"jpg", "image/jpeg"),
    ]
    assert client.metadata == [("media-1", "first image")]
    assert client.created == {
        "text": "hello",
        "media_ids": ["media-1", "media-2"],
        "reply_to": "123",
    }


def test_media_input_validation() -> None:
    urls, alt_texts = _validate_media_inputs(
        ["https://images.example.com/one.png"],
        ["description"],
    )
    assert urls == ["https://images.example.com/one.png"]
    assert alt_texts == ["description"]
    assert _validate_public_image_url("https://images.example.com/one.png").startswith(
        "https://"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        _validate_public_image_url("http://images.example.com/one.png")
    with pytest.raises(ValueError, match="same length"):
        _validate_media_inputs(
            ["https://images.example.com/one.png"],
            [],
        )
    with pytest.raises(ValueError, match="at most 4"):
        _validate_media_inputs(
            [f"https://images.example.com/{i}.png" for i in range(5)],
            None,
        )


def test_public_dns_rejects_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        twitter_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(ValueError, match="public IP"):
        _assert_public_dns("https://images.example.com/one.png")


def test_detect_image_mime() -> None:
    assert _detect_image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert _detect_image_mime(b"\xff\xd8\xffrest") == "image/jpeg"
    assert _detect_image_mime(b"RIFFxxxxWEBPrest") == "image/webp"
    with pytest.raises(ValueError, match="PNG, JPEG, or WebP"):
        _detect_image_mime(b"GIF89a")


def test_download_error_does_not_expose_url_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "TOPSECRET_QUERY_VALUE"

    class FailingOpener:
        def open(self, request, timeout):
            raise OSError(
                f"failed URL https://images.example.com/a.png?token={secret}"
            )

    monkeypatch.setattr(twitter_module, "_assert_public_dns", lambda url: None)
    monkeypatch.setattr(
        twitter_module.urllib.request,
        "build_opener",
        lambda handler: FailingOpener(),
    )
    with pytest.raises(BackendExecutionError) as exc_info:
        _download_public_image(
            f"https://images.example.com/a.png?token={secret}"
        )
    assert secret not in str(exc_info.value)


class FakePage:
    def __init__(self, items: list[int], next_page: "FakePage | None" = None):
        self._items = items
        self._next_page = next_page
        self.next_cursor = "next" if next_page is not None else None

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    async def next(self) -> "FakePage":
        return self._next_page or FakePage([])


@pytest.mark.asyncio
async def test_collect_twifork_pages_respects_limit() -> None:
    page = FakePage([1, 2], FakePage([3, 4], FakePage([5])))
    items, has_more = await _collect_twifork_pages(page, 3)
    assert items == [1, 2, 3]
    assert has_more is True


def test_validators() -> None:
    assert _validate_username("@OpenAI") == "OpenAI"
    assert _validate_post_ref("123456") == "123456"
    url = "https://x.com/OpenAI/status/123456"
    assert _validate_post_ref(url).endswith("/123456")
    assert _tweet_id_from_ref(url) == "123456"
