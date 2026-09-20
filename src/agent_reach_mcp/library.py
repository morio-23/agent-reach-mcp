"""Platform-neutral, local-only source registry and research library.

The original `sources` and `findings` tables are retained for rollback. The
first initialization copies them once, without deleting or rewriting records.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_X_USER = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_STATES = {"new", "reviewed", "ignored"}
_TAG = re.compile(r"^[^,\n\r\t]{1,40}$")
_COLLECTION = re.compile(r"^[^\n\r\t]{1,80}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _web_url(text: str) -> str:
    text = text.strip()
    if len(text) > 1500 or any(char.isspace() for char in text):
        raise ValueError("invalid web URL")
    parts = urlsplit(text)
    if (parts.scheme not in {"https", "http"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.fragment or not parts.netloc):
        raise ValueError("web URL must be an HTTP(S) URL without credentials or fragment")
    try:
        _ = parts.port
    except ValueError:
        raise ValueError("invalid web URL port") from None
    # Network-layer SSRF checks remain the responsibility of Gateway.read_url.
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


class LibraryStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_registry(
                  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL,
                  label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                  UNIQUE(kind,value)
                );
                CREATE TABLE IF NOT EXISTS library_items(
                  item_id TEXT PRIMARY KEY, platform TEXT NOT NULL,
                  external_id TEXT NOT NULL, item_type TEXT NOT NULL DEFAULT 'post',
                  title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
                  url TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
                  published_at TEXT NOT NULL DEFAULT '', captured_at TEXT NOT NULL,
                  backend TEXT NOT NULL DEFAULT 'unknown',
                  state TEXT NOT NULL DEFAULT 'new', notes TEXT NOT NULL DEFAULT '',
                  UNIQUE(platform,external_id)
                );
                CREATE TABLE IF NOT EXISTS library_tags(
                  item_id TEXT NOT NULL REFERENCES library_items(item_id) ON DELETE CASCADE,
                  tag TEXT NOT NULL, PRIMARY KEY(item_id,tag)
                );
                CREATE TABLE IF NOT EXISTS library_collections(
                  name TEXT PRIMARY KEY, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS library_memberships(
                  item_id TEXT NOT NULL REFERENCES library_items(item_id) ON DELETE CASCADE,
                  collection_name TEXT NOT NULL REFERENCES library_collections(name) ON DELETE CASCADE,
                  PRIMARY KEY(item_id,collection_name)
                );
                CREATE TABLE IF NOT EXISTS console_schema_migrations(
                  name TEXT PRIMARY KEY, migrated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS library_items_captured_at
                  ON library_items(captured_at DESC);
                """
            )
            migrated = db.execute(
                "SELECT 1 FROM console_schema_migrations WHERE name='generic_v1'"
            ).fetchone()
            if not migrated:
                # First startup after upgrade: preserve existing X sources and
                # annotations, including review state, without altering old tables.
                db.execute(
                    """INSERT OR IGNORE INTO source_registry(id,kind,value,created_at)
                    SELECT id,kind,value,created_at FROM sources"""
                )
                db.execute(
                    """INSERT OR IGNORE INTO library_items(
                      item_id,platform,external_id,item_type,title,content,url,
                      author,published_at,captured_at,backend,state,notes)
                    SELECT 'x:' || post_id,'x',post_id,'post','',content,
                      COALESCE(url,''),COALESCE(author,''),COALESCE(published_at,''),
                      captured_at,COALESCE(source_backend,'unknown'),state,notes
                    FROM findings"""
                )
                db.execute(
                    """INSERT OR IGNORE INTO library_tags(item_id,tag)
                    SELECT 'x:' || post_id,category FROM findings
                    WHERE category NOT IN ('other','')"""
                )
                db.execute(
                    "INSERT INTO console_schema_migrations VALUES(?,?)",
                    ("generic_v1", _now()),
                )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def sources(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,kind,value,label,created_at FROM source_registry ORDER BY id DESC LIMIT 200"
            )]

    def add_source(self, kind: str, value: str, label: str = "") -> dict[str, Any]:
        if kind not in {"user", "query", "web"}:
            raise ValueError("unsupported source kind")
        value = value.strip().lstrip("@") if kind == "user" else value.strip()
        if kind == "user" and not _X_USER.fullmatch(value):
            raise ValueError("invalid X username")
        if kind == "query" and not 1 <= len(value) <= 200:
            raise ValueError("invalid X search query")
        if kind == "web":
            value = _web_url(value)
        label = label.strip()
        if len(label) > 100:
            raise ValueError("source label is too long")
        with self.lock, self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO source_registry(kind,value,label,created_at) VALUES(?,?,?,?)",
                (kind, value, label, _now()),
            )
            row = db.execute(
                "SELECT id,kind,value,label,created_at FROM source_registry WHERE kind=? AND value=?",
                (kind, value),
            ).fetchone()
            assert row is not None
            return dict(row)

    def remove_source(self, source_id: int) -> None:
        with self.lock, self._connect() as db:
            db.execute("DELETE FROM source_registry WHERE id=?", (source_id,))

    def source(self, source_id: int) -> dict[str, Any]:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT id,kind,value,label FROM source_registry WHERE id=?", (source_id,)
            ).fetchone()
        if row is None:
            raise ValueError("source not found")
        return dict(row)

    def ingest(self, result: dict[str, Any]) -> dict[str, Any]:
        source = result.get("source") or {}
        platform = str(source.get("platform") or "").strip().lower()
        backend = str(source.get("backend") or "unknown")[:100]
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,29}", platform):
            raise ValueError("invalid platform")
        rows = result.get("items") or []
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("invalid item count")
        inserted = 0
        with self.lock, self._connect() as db:
            for item in rows:
                if not isinstance(item, dict):
                    continue
                external_id = str(item.get("id") or "")
                if not external_id or len(external_id) > 300:
                    continue
                item_id = f"{platform}:{external_id}"
                author = item.get("author") or {}
                if not isinstance(author, dict):
                    author = {}
                cursor = db.execute(
                    """INSERT OR IGNORE INTO library_items(
                      item_id,platform,external_id,item_type,title,content,url,
                      author,published_at,captured_at,backend)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (item_id, platform, external_id,
                     str(item.get("type") or "document")[:50],
                     str(item.get("title") or "")[:500],
                     str(item.get("content") or "")[:100000],
                     str(item.get("url") or "")[:1500],
                     str(author.get("username") or author.get("display_name") or "")[:100],
                     str(item.get("published_at") or "")[:64], _now(), backend),
                )
                inserted += cursor.rowcount
        return {"fetched": len(rows), "new": inserted, "backend": backend,
                "warnings": result.get("warnings") or []}

    def ingest_web(self, result: dict[str, Any]) -> dict[str, Any]:
        url = _web_url(str(result.get("url") or ""))
        external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        payload = {
            "source": {"platform": "web", "backend": (result.get("source") or {}).get("backend") or "web"},
            "items": [{
                "id": external_id, "type": "page", "title": url,
                "content": result.get("content") or "",
                "url": url, "published_at": "",
            }],
            "warnings": result.get("warnings") or [],
        }
        return self.ingest(payload)

    def items(self, *, state: str = "", collection: str = "", query: str = "") -> list[dict[str, Any]]:
        if state and state not in _STATES:
            raise ValueError("invalid state")
        if len(collection) > 80 or len(query) > 200:
            raise ValueError("filter is too long")
        conditions = []
        params: list[str] = []
        if state:
            conditions.append("i.state=?")
            params.append(state)
        if collection:
            conditions.append("EXISTS(SELECT 1 FROM library_memberships m WHERE m.item_id=i.item_id AND m.collection_name=?)")
            params.append(collection)
        if query:
            conditions.append("(i.title LIKE ? OR i.content LIKE ? OR i.author LIKE ?)")
            params += [f"%{query}%"] * 3
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.lock, self._connect() as db:
            rows = db.execute(
                "SELECT i.* FROM library_items i" + where +
                " ORDER BY i.captured_at DESC LIMIT 300", params
            ).fetchall()
            return [
                {**dict(row),
                 "tags": [tag[0] for tag in db.execute(
                     "SELECT tag FROM library_tags WHERE item_id=? ORDER BY tag", (row["item_id"],)
                 )],
                 "collections": [member[0] for member in db.execute(
                     "SELECT collection_name FROM library_memberships WHERE item_id=? ORDER BY collection_name",
                     (row["item_id"],)
                 )]}
                for row in rows
            ]

    def collections(self) -> list[str]:
        with self.lock, self._connect() as db:
            return [r[0] for r in db.execute(
                "SELECT name FROM library_collections ORDER BY name LIMIT 200"
            )]

    def review(self, item_id: str, state: str, notes: str, tags: list[str],
               collections: list[str]) -> None:
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 340:
            raise ValueError("invalid item id")
        if state not in _STATES or not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError("invalid review")
        if (not isinstance(tags, list) or len(tags) > 15
                or any(not isinstance(tag, str) or not _TAG.fullmatch(tag)
                       for tag in tags)):
            raise ValueError("invalid tags")
        if (not isinstance(collections, list) or len(collections) > 10
                or any(not isinstance(name, str) or not _COLLECTION.fullmatch(name)
                       for name in collections)):
            raise ValueError("invalid collections")
        tags = list(dict.fromkeys(tag.strip() for tag in tags))
        collections = list(dict.fromkeys(name.strip() for name in collections))
        if not all(tags) or not all(collections):
            raise ValueError("empty tag or collection")
        with self.lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE library_items SET state=?,notes=? WHERE item_id=?",
                (state, notes, item_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("item not found")
            db.execute("DELETE FROM library_tags WHERE item_id=?", (item_id,))
            db.executemany(
                "INSERT INTO library_tags(item_id,tag) VALUES(?,?)",
                [(item_id, tag) for tag in tags],
            )
            db.execute("DELETE FROM library_memberships WHERE item_id=?", (item_id,))
            db.executemany(
                "INSERT OR IGNORE INTO library_collections(name,created_at) VALUES(?,?)",
                [(name, _now()) for name in collections],
            )
            db.executemany(
                "INSERT INTO library_memberships(item_id,collection_name) VALUES(?,?)",
                [(item_id, name) for name in collections],
            )
