"""News deduplication: URL exact match + title fuzzy match."""
from difflib import SequenceMatcher

from loguru import logger

from src.models import NewsItem


def _title_similarity(a: str, b: str) -> float:
    """Return similarity ratio between two titles."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def deduplicate(
    items: list[NewsItem], threshold: float = 0.80
) -> list[NewsItem]:
    """Deduplicate news items by URL (exact) then by title similarity."""
    if not items:
        return []

    # Pass 1: exact URL dedup
    seen_urls: set[str] = set()
    url_deduped: list[NewsItem] = []
    for item in items:
        if item.url and item.url not in seen_urls:
            seen_urls.add(item.url)
            url_deduped.append(item)
        elif not item.url:
            url_deduped.append(item)

    # Pass 2: title similarity dedup
    result: list[NewsItem] = []
    for item in url_deduped:
        is_dup = False
        for kept in result:
            if _title_similarity(item.title, kept.title) >= threshold:
                is_dup = True
                break
        if not is_dup:
            result.append(item)

    removed = len(items) - len(result)
    if removed > 0:
        logger.info(
            f"Dedup removed {removed} duplicate items, {len(result)} remaining"
        )
    return result
