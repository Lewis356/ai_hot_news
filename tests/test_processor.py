from datetime import datetime, timedelta, timezone
from src.processor.dedup import deduplicate
from src.processor.filter import filter_recent
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


# --- Dedup tests ---

def test_dedup_removes_exact_url_duplicates():
    items = [
        NewsItem("A", "http://a.com/1", "", "S1", now()),
        NewsItem("A again", "http://a.com/1", "", "S2", now()),
    ]
    result = deduplicate(items)
    assert len(result) == 1


def test_dedup_removes_similar_title():
    items = [
        NewsItem(
            "GPT-5 officially announced by OpenAI",
            "http://a.com/1", "", "S1", now()
        ),
        NewsItem(
            "GPT-5 officially announced by OpenAI!",
            "http://a.com/2", "", "S2", now()
        ),
    ]
    result = deduplicate(items, threshold=0.80)
    assert len(result) == 1


def test_dedup_keeps_different_titles():
    items = [
        NewsItem("GPT-5 announced", "http://a.com/1", "", "S1", now()),
        NewsItem("Claude 5 released", "http://a.com/2", "", "S2", now()),
    ]
    result = deduplicate(items, threshold=0.80)
    assert len(result) == 2


def test_dedup_empty_list():
    assert deduplicate([]) == []


def test_dedup_keeps_items_without_url():
    """Items without URL should be kept (can't dedup by URL)."""
    items = [
        NewsItem("Same Title", "", "", "S1", now()),
        NewsItem("Same Title", "", "", "S2", now()),
    ]
    result = deduplicate(items, threshold=0.80)
    # Same title -> one should be removed by title similarity
    assert len(result) == 1


# --- Filter tests ---

def test_filter_keeps_recent_items():
    recent = NewsItem(
        "Recent", "http://a.com/1", "", "S1",
        now() - timedelta(hours=2)
    )
    items = [recent]
    result = filter_recent(items, hours=24)
    assert len(result) == 1


def test_filter_removes_old_items():
    old = NewsItem(
        "Old", "http://a.com/1", "", "S1",
        now() - timedelta(hours=48)
    )
    items = [old]
    result = filter_recent(items, hours=24)
    assert len(result) == 0


def test_filter_keeps_items_without_valid_date():
    """RSS without published date (before 2020 epoch) should be kept."""
    item = NewsItem(
        "No Date", "http://a.com/1", "", "S1",
        published_at=datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    items = [item]
    result = filter_recent(items, hours=24)
    assert len(result) == 1


def test_filter_mixed_items():
    recent = NewsItem(
        "Recent", "http://a.com/1", "", "S1",
        now() - timedelta(hours=1)
    )
    old = NewsItem(
        "Old", "http://a.com/2", "", "S1",
        now() - timedelta(hours=72)
    )
    result = filter_recent([recent, old], hours=24)
    assert len(result) == 1
    assert result[0].title == "Recent"
