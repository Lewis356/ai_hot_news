"""Time-based filtering: keep only recent news items."""
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.models import NewsItem

# Items published before this date are treated as "no valid date" and kept
_EPOCH_CUTOFF = datetime(2020, 1, 1, tzinfo=timezone.utc)


def filter_recent(items: list[NewsItem], hours: int = 24) -> list[NewsItem]:
    """Filter items to only those published within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result: list[NewsItem] = []
    for item in items:
        if item.published_at < _EPOCH_CUTOFF:
            # No valid published date — keep it
            result.append(item)
        elif item.published_at >= cutoff:
            result.append(item)
    removed = len(items) - len(result)
    if removed > 0:
        logger.info(
            f"Time filter removed {removed} old items, {len(result)} remaining"
        )
    return result
