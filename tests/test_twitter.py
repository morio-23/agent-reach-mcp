from types import SimpleNamespace

import pytest

from agent_reach_mcp.twitter import (
    _collect_twifork_pages,
    _normalize_tweet,
    _normalize_twifork_tweet,
    _to_single_result,
    _tweet_id_from_ref,
    _validate_post_ref,
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
