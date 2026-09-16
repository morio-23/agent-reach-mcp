from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / ".dogfood" / "profile.json"
RUNS_DIR = ROOT / ".dogfood" / "runs"

EXPECTED_TOOLS = {
    "get_capabilities",
    "read_url",
    "search_x",
    "get_x_user_posts",
    "get_x_post",
    "get_youtube_transcript",
}


class DogfoodError(RuntimeError):
    pass


def _load_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DogfoodError(
            f"profile not found: {path}. Copy dogfood.example.json to "
            ".dogfood/profile.json and edit it for your real use case."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DogfoodError(f"could not read profile {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DogfoodError("dogfood profile must be a JSON object")
    return data


def _payload(result: Any) -> dict[str, Any]:
    if getattr(result, "is_error", False):
        raise DogfoodError(_result_text(result) or "MCP tool returned an error")

    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if hasattr(structured, "model_dump"):
        structured = structured.model_dump()
    if isinstance(structured, dict):
        return structured

    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate

    raise DogfoodError("MCP tool did not return structured JSON output")


def _result_text(result: Any) -> str:
    chunks: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks)[:1000]


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("items")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _content_chars(payload: dict[str, Any]) -> int:
    value = payload.get("content")
    return len(value) if isinstance(value, str) else 0


def _source(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("source")
    return raw if isinstance(raw, dict) else {}


def _step_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    items = _items(payload)
    if "items" in payload:
        summary["items"] = len(items)
    if "content" in payload:
        summary["content_chars"] = _content_chars(payload)
    source = _source(payload)
    if source:
        summary["source"] = {
            "platform": source.get("platform"),
            "backend": source.get("backend"),
        }
    if "truncated" in payload:
        summary["truncated"] = bool(payload.get("truncated"))
    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        summary["warnings"] = [str(x)[:200] for x in warnings[:5]]
    return summary


async def _call(
    client: Client, name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = await client.call_tool(name, arguments)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return _payload(result), elapsed_ms


async def _record(
    report: dict[str, Any],
    label: str,
    operation: Callable[[], Awaitable[tuple[dict[str, Any], float]]],
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    try:
        payload, elapsed_ms = await operation()
        if validate is not None:
            validate(payload)
        report["steps"][label] = {
            "status": "passed",
            "elapsed_ms": round(elapsed_ms, 1),
            **_step_summary(payload),
        }
        print(f"OK: {label} ({elapsed_ms:.0f} ms)")
        return payload
    except Exception as exc:
        report["steps"][label] = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
        print(f"FAIL: {label}: {exc}", file=sys.stderr)
        return None


def _require_content(payload: dict[str, Any]) -> None:
    if _content_chars(payload) <= 0:
        raise DogfoodError("tool returned empty content")


def _require_items(payload: dict[str, Any]) -> None:
    if not _items(payload):
        raise DogfoodError("tool returned zero items")


def _first_post_ref(payload: dict[str, Any]) -> str | None:
    for item in _items(payload):
        url = item.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return url
        post_id = item.get("id")
        if post_id is not None:
            return str(post_id)
    return None


async def _dogfood(profile: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(profile.get("endpoint") or "http://127.0.0.1:8080/mcp")
    token_env = profile.get("token_env")
    token = os.environ.get(str(token_env)) if token_env else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "steps": {},
    }

    async with httpx2.AsyncClient(headers=headers, timeout=45.0) as http_client:
        transport = streamable_http_client(url=endpoint, http_client=http_client)
        async with Client(transport) as client:
            tools_result = await client.list_tools()
            names = {tool.name for tool in tools_result.tools}
            missing = sorted(EXPECTED_TOOLS - names)
            if missing:
                raise DogfoodError(
                    f"MCP endpoint is missing expected tools: {', '.join(missing)}"
                )
            report["protocol"] = str(client.protocol_version)
            report["tools"] = sorted(names)
            print(f"MCP protocol: {client.protocol_version}")
            print("Tools:", ", ".join(sorted(names)))

            await _record(
                report,
                "get_capabilities",
                lambda: _call(client, "get_capabilities", {"refresh": True}),
            )

            read_url = profile.get("read_url")
            if isinstance(read_url, str) and read_url.strip():
                await _record(
                    report,
                    "read_url",
                    lambda: _call(client, "read_url", {"url": read_url.strip()}),
                    _require_content,
                )

            x = profile.get("x")
            if isinstance(x, dict) and x.get("enabled", True):
                username = str(x.get("username") or "").strip().lstrip("@")
                query = str(x.get("query") or "").strip()
                limit = int(x.get("limit") or 5)
                if not username or not query:
                    raise DogfoodError(
                        "x.username and x.query are required when X dogfood is enabled"
                    )

                user_posts = await _record(
                    report,
                    "get_x_user_posts",
                    lambda: _call(
                        client,
                        "get_x_user_posts",
                        {"username": username, "limit": limit},
                    ),
                    _require_items,
                )

                post_ref = str(x.get("post") or "").strip()
                if not post_ref and user_posts is not None:
                    post_ref = _first_post_ref(user_posts) or ""
                if post_ref:
                    await _record(
                        report,
                        "get_x_post",
                        lambda: _call(client, "get_x_post", {"post": post_ref}),
                        _require_items,
                    )
                else:
                    report["steps"]["get_x_post"] = {
                        "status": "failed",
                        "error": "no post reference was available from get_x_user_posts",
                    }

                search_args: dict[str, Any] = {"query": query, "limit": limit}
                if x.get("search_from_user", True):
                    search_args["from_user"] = username
                require_search_results = bool(
                    x.get("require_search_results", True)
                )
                await _record(
                    report,
                    "search_x",
                    lambda: _call(client, "search_x", search_args),
                    _require_items if require_search_results else None,
                )

            youtube = profile.get("youtube")
            if isinstance(youtube, dict) and youtube.get("enabled", True):
                video_url = str(youtube.get("url") or "").strip()
                if not video_url:
                    raise DogfoodError(
                        "youtube.url is required when YouTube dogfood is enabled"
                    )
                arguments: dict[str, Any] = {"url": video_url}
                languages = youtube.get("languages")
                if isinstance(languages, list) and languages:
                    arguments["languages"] = [str(x) for x in languages]
                await _record(
                    report,
                    "get_youtube_transcript",
                    lambda: _call(
                        client, "get_youtube_transcript", arguments
                    ),
                    _require_content,
                )

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    failures = [
        name
        for name, value in report["steps"].items()
        if isinstance(value, dict) and value.get("status") == "failed"
    ]
    report["passed"] = not failures
    report["failed_steps"] = failures
    return report


def _write_report(report: dict[str, Any]) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RUNS_DIR / f"{stamp}.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise a running agent-reach-mcp endpoint "
            "using a real dogfood profile."
        )
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args()

    try:
        profile = _load_profile(args.profile)
        report = asyncio.run(_dogfood(profile))
        path = _write_report(report)
        print(f"Report: {path.relative_to(ROOT)}")
        if not report["passed"]:
            raise SystemExit(1)
        print("Dogfood run passed")
    except (DogfoodError, OSError, ValueError) as exc:
        print(f"Dogfood run failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
