"""Time-based filtering: keep only recent news items."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from src.models import NewsItem


def filter_recent(
    items: list[NewsItem],
    hours: int = 24,
    *,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Filter items to only those published within the last N hours."""
    reference_time = now or datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(hours=hours)
    result: list[NewsItem] = []
    for item in items:
        if item.published_at is not None and item.published_at >= cutoff:
            result.append(item)
    removed = len(items) - len(result)
    if removed > 0:
        logger.info(
            f"Time filter removed {removed} old items, {len(result)} remaining"
        )
    return result
