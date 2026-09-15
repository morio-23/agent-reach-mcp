from agent_reach_mcp.twitter import _normalize_tweet, _validate_post_ref, _validate_username


def test_normalize_tweet() -> None:
    item = _normalize_tweet({"id": "123", "text": "hello", "createdAtISO": "2026-09-15T00:00:00Z", "author": {"id": "u1", "screenName": "example", "name": "Example"}, "metrics": {"likes": 3}})
    assert item.url == "https://x.com/example/status/123"
    assert item.author is not None
    assert item.author.username == "example"
    assert item.metadata["metrics"]["likes"] == 3


def test_validators() -> None:
    assert _validate_username("@OpenAI") == "OpenAI"
    assert _validate_post_ref("123456") == "123456"
    assert _validate_post_ref("https://x.com/OpenAI/status/123456").endswith("/123456")
