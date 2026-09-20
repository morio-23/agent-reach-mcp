"""Local-only operator console for registered X sources and reviewable findings.

Deliberately separate from the public MCP endpoint. This module does not expose
posting; a write workflow requires a distinct, audited approval implementation.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from .config import Settings, TransportMode
from .gateway import Gateway
from .library import LibraryStore

_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_KINDS = {"event", "product", "deadline", "other"}
_STATES = {"new", "reviewed", "ignored"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConsoleStore:
    """A small, persistent, local-only review store; never contains X credentials."""

    def __init__(self, database: Path):
        self.database = database
        self.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = Lock()
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('user','query')),
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(kind, value)
                );
                CREATE TABLE IF NOT EXISTS findings (
                    post_id TEXT PRIMARY KEY,
                    author TEXT,
                    content TEXT NOT NULL,
                    url TEXT,
                    published_at TEXT,
                    source_backend TEXT,
                    captured_at TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'other',
                    state TEXT NOT NULL DEFAULT 'new',
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )
        self.library = LibraryStore(database)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def sources(self) -> list[dict[str, Any]]:
        return self.library.sources()

    def add_source(self, kind: str, value: str, label: str = "") -> dict[str, Any]:
        source = self.library.add_source(kind, value, label)
        # Preserve the original X source registry for a safe rollback.
        if source["kind"] in {"user", "query"}:
            with self.lock, self._connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO sources(id,kind,value,created_at) VALUES(?,?,?,?)",
                    (source["id"], source["kind"], source["value"], source["created_at"]),
                )
        return source

    def remove_source(self, source_id: int) -> None:
        source = self.library.source(source_id)
        self.library.remove_source(source_id)
        if source["kind"] in {"user", "query"}:
            with self.lock, self._connect() as db:
                db.execute(
                    "DELETE FROM sources WHERE kind=? AND value=?",
                    (source["kind"], source["value"]),
                )

    def source(self, source_id: int) -> dict[str, Any]:
        return self.library.source(source_id)

    def findings(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM findings ORDER BY captured_at DESC LIMIT 300"
            )]

    def save_findings(self, result: dict[str, Any]) -> dict[str, Any]:
        backend = str((result.get("source") or {}).get("backend") or "unknown")
        items = result.get("items") or []
        inserted = 0
        with self.lock, self._connect() as db:
            for item in items:
                if not isinstance(item, dict):
                    continue
                post_id = str(item.get("id") or "")
                if not re.fullmatch(r"\d{1,30}", post_id):
                    continue
                author = item.get("author") or {}
                if not isinstance(author, dict):
                    author = {}
                cursor = db.execute(
                    """INSERT OR IGNORE INTO findings(
                        post_id,author,content,url,published_at,source_backend,captured_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        post_id,
                        str(author.get("username") or "")[:30],
                        str(item.get("content") or "")[:5000],
                        str(item.get("url") or "")[:1000],
                        str(item.get("published_at") or "")[:64],
                        backend,
                        _utc_now(),
                    ),
                )
                inserted += cursor.rowcount
        # Compatibility endpoint retains its original X-only counters and
        # review rows. The new cross-platform library is the source of truth
        # for the generic UI, migrated from older findings on first startup.
        library_summary = self.library.ingest({
            **result, "source": {**(result.get("source") or {}), "platform": "x"}
        })
        summary = {"fetched": len(items), "new": inserted, "backend": backend,
                   "warnings": result.get("warnings") or []}
        if library_summary["updated"]:
            summary["updated"] = library_summary["updated"]
        return summary

    def review(self, post_id: str, category: str, state: str, notes: str) -> None:
        if not re.fullmatch(r"\d{1,30}", post_id):
            raise ValueError("invalid post id")
        if category not in _KINDS or state not in _STATES or len(notes) > 2000:
            raise ValueError("invalid review")
        with self.lock, self._connect() as db:
            result = db.execute(
                "UPDATE findings SET category=?,state=?,notes=? WHERE post_id=?",
                (category, state, notes, post_id),
            )
            if result.rowcount != 1:
                raise ValueError("finding not found")


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], access_token: str,
                 store: ConsoleStore, gateway: Gateway):
        super().__init__(address, ConsoleHandler)
        self.access_token = access_token
        self.store = store
        self.gateway = gateway
        self.research_lock = Lock()

    def research(self, source: dict[str, Any], limit: int) -> dict[str, Any]:
        if source["kind"] == "user":
            result = asyncio.run(self.gateway.get_x_user_posts(source["value"], limit))
        elif source["kind"] == "query":
            result = asyncio.run(self.gateway.search_x(source["value"], limit))
        elif source["kind"] == "web":
            result = asyncio.run(self.gateway.read_url(source["value"]))
        else:
            raise ValueError("unsupported source kind")
        summary = (self.store.library.ingest_web(result)
                   if source["kind"] == "web"
                   else self.store.save_findings(result))
        self.store.library.record_run(source, status="success", summary=summary)
        return summary


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def _allowed_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.server.server_port}",
                        f"localhost:{self.server.server_port}"}

    def _response(self, code: int, payload: Any, *, html: bool = False) -> None:
        body = (payload.encode("utf-8") if html
                else json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html
                         else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _authenticated(self) -> bool:
        supplied = self.headers.get("X-Console-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.server.access_token)

    def _preflight(self, *, write: bool = False) -> bool:
        if not self._allowed_host():
            self._response(403, {"error": "invalid host"})
            return False
        if write:
            origin = self.headers.get("Origin", "")
            if origin not in {f"http://127.0.0.1:{self.server.server_port}",
                              f"http://localhost:{self.server.server_port}"}:
                self._response(403, {"error": "invalid origin"})
                return False
        if not self._authenticated():
            self._response(401, {"error": "console access token required"})
            return False
        return True

    def _json_body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if not 1 <= size <= 16_384 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("expected application/json body (max 16 KiB)")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def _query_arg(self, name: str) -> str:
        from urllib.parse import parse_qs

        parts = parse_qs(urlsplit(self.path).query)
        return parts.get(name, [""])[0]

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not self._allowed_host():
            self._response(403, {"error": "invalid host"})
            return
        if path in {"/", "/console.js", "/console.css"}:
            filename = {"/": "console.html", "/console.js": "console.js",
                        "/console.css": "console.css"}[path]
            content = (Path(__file__).parent / "console_assets" / filename).read_bytes()
            kind = ("text/html" if filename.endswith(".html") else
                    "text/javascript" if filename.endswith(".js") else "text/css")
            self.send_response(200)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(content)
            return
        if not self._preflight():
            return
        if path == "/api/sources":
            self._response(200, {"sources": self.server.store.sources()})
        elif path == "/api/items":
            try:
                items = self.server.store.library.items(
                    state=self._query_arg("state"),
                    collection=self._query_arg("collection"),
                    query=self._query_arg("q"),
                )
            except ValueError as exc:
                self._response(400, {"error": str(exc)})
                return
            self._response(200, {"items": items})
        elif path == "/api/collections":
            self._response(200, {"collections": self.server.store.library.collections()})
        elif path == "/api/runs":
            self._response(200, {"runs": self.server.store.library.runs()})
        elif path == "/api/revisions":
            try:
                revisions = self.server.store.library.revisions(self._query_arg("item_id"))
            except ValueError as exc:
                self._response(400, {"error": str(exc)})
                return
            self._response(200, {"revisions": revisions})
        elif path == "/api/findings":
            self._response(200, {"findings": self.server.store.findings()})
        else:
            self._response(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._preflight(write=True):
            return
        try:
            data = self._json_body()
            path = urlsplit(self.path).path
            if path == "/api/sources":
                result = self.server.store.add_source(
                    str(data.get("kind") or ""), str(data.get("value") or ""),
                    str(data.get("label") or ""))
                self._response(200, {"source": result})
            elif path == "/api/sources/delete":
                self.server.store.remove_source(int(data["source_id"]))
                self._response(200, {"ok": True})
            elif path == "/api/research":
                source = self.server.store.source(int(data["source_id"]))
                limit = int(data.get("limit", 10))
                if not 1 <= limit <= 40:
                    raise ValueError("limit must be 1 to 40")
                if not self.server.research_lock.acquire(blocking=False):
                    self._response(409, {"error": "research already running"})
                    return
                try:
                    try:
                        summary = self.server.research(source, limit)
                    except Exception:
                        self.server.store.library.record_run(
                            source, status="failed",
                            summary={"message": "調査失敗（接続・認証・取得元を確認）"},
                        )
                        raise
                finally:
                    self.server.research_lock.release()
                self._response(200, summary)
            elif path == "/api/research/batch":
                source_ids = data.get("source_ids")
                limit = data.get("limit", 10)
                if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 5
                        or any(type(sid) is not int or sid <= 0 for sid in source_ids)
                        or len(set(source_ids)) != len(source_ids)):
                    raise ValueError("choose 1-5 distinct source IDs")
                if type(limit) is not int or not 1 <= limit <= 10:
                    raise ValueError("batch limit must be 1-10")
                sources = [self.server.store.source(sid) for sid in source_ids]
                if not self.server.research_lock.acquire(blocking=False):
                    self._response(409, {"error": "research already running"})
                    return
                results = []
                try:
                    for source in sources:
                        try:
                            summary = self.server.research(source, limit)
                            results.append({"source_id": source["id"],
                                            "source_label": source.get("label") or source["value"],
                                            "status": "success", **summary})
                        except Exception:
                            # Each failure is isolated; never return credential-bearing
                            # backend exceptions to the browser.
                            self.server.store.library.record_run(
                                source, status="failed",
                                summary={"message": "調査失敗（接続・認証・取得元を確認）"},
                            )
                            results.append({"source_id": source["id"],
                                            "source_label": source.get("label") or source["value"],
                                            "status": "failed",
                                            "message": "調査失敗（接続・認証・取得元を確認）"})
                finally:
                    self.server.research_lock.release()
                self._response(200, {"results": results})
            elif path == "/api/items/review":
                self.server.store.library.review(
                    data.get("item_id"), data.get("state"), data.get("notes"),
                    data.get("tags"), data.get("collections"))
                self._response(200, {"ok": True})
            elif path == "/api/findings/review":
                self.server.store.review(
                    str(data.get("post_id") or ""),
                    str(data.get("category") or ""),
                    str(data.get("state") or ""),
                    str(data.get("notes") or ""))
                self._response(200, {"ok": True})
            else:
                self._response(404, {"error": "not found"})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self._response(400, {"error": str(exc)[:300]})
        except Exception:
            # Backend errors may contain signed URLs or credentials; never echo
            # raw exceptions to the browser or console log.
            self._response(502, {"error": "research failed; inspect backend health"})

    def do_OPTIONS(self) -> None:
        self._response(405, {"error": "CORS not supported"})

    def log_message(self, format: str, *args: Any) -> None:
        # Access tokens remain in headers, not logged.
        return


def main() -> None:
    token = os.environ.get("AGENT_REACH_CONSOLE_ACCESS_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("AGENT_REACH_CONSOLE_ACCESS_TOKEN must be at least 32 characters")
    port = int(os.environ.get("AGENT_REACH_CONSOLE_PORT", "8090"))
    if not 1 <= port <= 65535:
        raise SystemExit("invalid console port")
    os.umask(0o077)
    state_dir = Path(os.environ.get("AGENT_REACH_CONSOLE_STATE_DIR",
                                   "/home/appuser/.agent-reach"))
    # The console uses Gateway only for read operations. Docker's image defaults
    # describe the separate HTTP MCP service; do not inherit its remote
    # listener configuration here or weaken the MCP origin safety guard.
    gateway = Gateway(Settings(
        transport=TransportMode.STDIO,
        host="127.0.0.1",
        x_write_enabled=False,
    ))
    server = ConsoleServer(("0.0.0.0", port), token,
                           ConsoleStore(state_dir / "console.sqlite3"), gateway)
    print(f"AgentReach operator console listening on container port {port} (read-only)")
    server.serve_forever()


if __name__ == "__main__":
    main()
