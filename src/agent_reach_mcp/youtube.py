import asyncio
import html
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .errors import BackendExecutionError
from .models import TranscriptResult

_TAG_RE = re.compile(r"<[^>]+>")

class YoutubeAdapter:
    def __init__(self, max_text_chars: int, max_output_bytes: int):
        self._max_text_chars = max_text_chars
        self._max_output_bytes = max_output_bytes

    async def transcript(self, url: str, languages: list[str] | None = None) -> TranscriptResult:
        return await asyncio.to_thread(self._transcript_sync, url, languages)

    def _transcript_sync(self, url: str, languages: list[str] | None) -> TranscriptResult:
        _validate_youtube_url(url)
        languages = _normalize_languages(languages)
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise BackendExecutionError("yt-dlp is not installed") from exc
        with tempfile.TemporaryDirectory(prefix="agent-reach-mcp-") as tmp:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": languages, "subtitlesformat": "vtt", "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"), "noplaylist": True, "overwrites": True}
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            except Exception as exc:
                raise BackendExecutionError(f"yt-dlp failed to retrieve subtitles: {exc}") from exc
            if not isinstance(info, dict):
                raise BackendExecutionError("yt-dlp returned no video metadata")
            files = list(Path(tmp).glob("*.vtt"))
            if not files:
                raise BackendExecutionError("No subtitles were available; audio transcription fallback is disabled")
            selected = _select_vtt(files, languages)
            if selected.stat().st_size > self._max_output_bytes:
                raise BackendExecutionError("Subtitle file exceeded the configured size limit")
            content = _vtt_to_text(selected.read_text(encoding="utf-8", errors="replace"))
            if not content:
                raise BackendExecutionError("Subtitle file was empty after normalization")
            truncated = len(content) > self._max_text_chars
            if truncated:
                content = content[: self._max_text_chars]
            duration = info.get("duration")
            return TranscriptResult(url=str(info.get("webpage_url") or url), title=str(info.get("title")) if info.get("title") else None, video_id=str(info.get("id")) if info.get("id") else None, language=_language_from_filename(selected.name, str(info.get("id") or "")), content=content, duration_seconds=int(duration) if isinstance(duration, (int, float)) else None, truncated=truncated, warnings=["Transcript was truncated."] if truncated else [])

def _validate_youtube_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        raise ValueError("url must be an HTTPS YouTube URL")

def _normalize_languages(languages: list[str] | None) -> list[str]:
    if not languages:
        return ["ja", "en", "zh-Hans", "zh"]
    cleaned = []
    for language in languages[:8]:
        value = language.strip()
        if not value or len(value) > 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("invalid language tag")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned

def _select_vtt(files: list[Path], languages: list[str]) -> Path:
    def score(path: Path):
        for i, language in enumerate(languages):
            if f".{language}." in path.name:
                return i, path.name
        return len(languages), path.name
    return sorted(files, key=score)[0]

def _language_from_filename(filename: str, video_id: str) -> str | None:
    value = filename[len(video_id) + 1:] if video_id and filename.startswith(video_id + ".") else filename
    return value[:-4] if value.endswith(".vtt") else value

def _vtt_to_text(vtt: str) -> str:
    lines, previous = [], None
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION", "Kind:", "Language:")) or "-->" in line or line.isdigit():
            continue
        line = html.unescape(_TAG_RE.sub("", line)).strip()
        if line and line != previous:
            lines.append(line)
            previous = line
    return "\n".join(lines).strip()
