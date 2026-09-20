from pathlib import Path

import pytest

from agent_reach_mcp.console import ConsoleStore


def test_legacy_migration_preserves_sources_findings_and_reviews(tmp_path: Path) -> None:
    path = tmp_path / "console.sqlite3"
    original = ConsoleStore(path)
    old_source = original.add_source("user", "LoveLive_staff")
    original.save_findings({
        "source": {"backend": "twifork"},
        "items": [{
            "id": "1234567890", "author": {"username": "staff"},
            "content": "Original text", "url": "https://x.com/staff/status/1234567890",
        }],
    })
    original.review("1234567890", "event", "reviewed", "Original note")
    # Simulate a database created by the old version before generic_v1 migration.
    import sqlite3

    with sqlite3.connect(path) as db:
        for table in ("source_registry", "library_items", "library_tags",
                      "library_collections", "library_memberships",
                      "console_schema_migrations"):
            db.execute(f"DROP TABLE IF EXISTS {table}")
    migrated = ConsoleStore(path)
    assert migrated.sources()[0]["id"] == old_source["id"]
    item = migrated.library.items()[0]
    assert item["item_id"] == "x:1234567890"
    assert item["state"] == "reviewed"
    assert item["notes"] == "Original note"
    assert item["tags"] == ["event"]
    migrated.remove_source(old_source["id"])
    # A deleted source must not reappear on a subsequent restart.
    assert ConsoleStore(path).sources() == []


def test_cross_platform_identity_tags_collections_and_filtering(tmp_path: Path) -> None:
    library = ConsoleStore(tmp_path / "console.sqlite3").library
    assert library.ingest({
        "source": {"platform": "x", "backend": "twitter-cli"},
        "items": [{"id": "123", "type": "post", "content": "A finding"}],
    })["new"] == 1
    assert library.ingest_web({
        "url": "https://example.com/news", "content": "Web finding",
        "source": {"backend": "Jina Reader"},
    })["new"] == 1
    assert library.ingest_web({
        "url": "https://example.com/news", "content": "Web finding updated",
        "source": {"backend": "Jina Reader"},
    })["new"] == 0
    items = library.items()
    assert {item["platform"] for item in items} == {"x", "web"}
    x_id = next(item["item_id"] for item in items if item["platform"] == "x")
    library.review(x_id, "reviewed", "Reusable research", ["research", "event"],
                   ["Project A", "Shared"])
    selected = library.items(state="reviewed", collection="Project A", query="finding")
    assert len(selected) == 1
    assert selected[0]["tags"] == ["event", "research"]
    assert selected[0]["collections"] == ["Project A", "Shared"]
    assert library.collections() == ["Project A", "Shared"]
    assert ConsoleStore(tmp_path / "console.sqlite3").library.items(
        collection="Shared")[0]["notes"] == "Reusable research"


def test_generic_source_validation_and_rejection(tmp_path: Path) -> None:
    store = ConsoleStore(tmp_path / "console.sqlite3")
    web = store.add_source("web", "https://example.com/news", "Tech news")
    assert web["label"] == "Tech news"
    assert store.add_source("web", "https://example.com/news")["id"] == web["id"]
    for invalid in ("file:///etc/passwd", "https://user:pass@example.com",
                    "http://127.0.0.1/#fragment", "not a url"):
        with pytest.raises(ValueError):
            store.add_source("web", invalid)
    with pytest.raises(ValueError):
        store.library.review("x:does-not-exist", "new", "", [], [])
    with pytest.raises(ValueError):
        store.library.review("x:123", "new", "", ["bad\ntag"], [])
    with pytest.raises(ValueError):
        store.library.items(state="invalid")
