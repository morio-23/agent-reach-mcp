from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AuthorInfo(BaseModel):
    id: str | None = None
    username: str | None = None
    display_name: str | None = None

class ContentItem(BaseModel):
    id: str | None = None
    platform: str
    type: str
    content: str
    url: str | None = None
    title: str | None = None
    author: AuthorInfo | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class SourceInfo(BaseModel):
    platform: str
    backend: str

class ItemResult(BaseModel):
    items: list[ContentItem]
    source: SourceInfo
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)

class ReadUrlResult(BaseModel):
    url: str
    content: str
    source: SourceInfo = Field(default_factory=lambda: SourceInfo(platform="web", backend="Jina Reader"))
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)

class TranscriptResult(BaseModel):
    url: str
    title: str | None = None
    video_id: str | None = None
    language: str | None = None
    content: str
    duration_seconds: int | None = None
    source: SourceInfo = Field(default_factory=lambda: SourceInfo(platform="youtube", backend="yt-dlp"))
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
