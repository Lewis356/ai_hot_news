"""Data models for AI news pipeline."""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NewsItem:
    """Raw news item fetched from an RSS feed."""
    title: str
    url: str
    summary: str
    source: str
    published_at: datetime
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvaluatedItem:
    """News item after AI evaluation, summarization, and ranking."""
    title: str
    url: str
    source: str
    chinese_summary: str
    importance: int
    keywords: list[str]
    published_at: datetime
