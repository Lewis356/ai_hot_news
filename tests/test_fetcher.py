from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.fetcher.rss_fetcher import fetch_single, fetch_all
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def _make_entry(title="", link="", summary="", published_parsed=None):
    """Create a feedparser-like entry with attribute access."""
    return SimpleNamespace(
        title=title,
        link=link,
        summary=summary,
        published_parsed=published_parsed,
    )


def test_fetch_single_returns_news_items():
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = [
        _make_entry(
            title="GPT-5 Announced",
            link="https://example.com/gpt5",
            summary="OpenAI announces GPT-5",
            published_parsed=(2026, 6, 23, 10, 0, 0, 0, 0, 0),
        )
    ]
    with patch("feedparser.parse", return_value=mock_feed):
        items = fetch_single("TestSource", "https://example.com/rss", timeout=10)
        assert len(items) == 1
        assert items[0].title == "GPT-5 Announced"
        assert items[0].source == "TestSource"
        assert items[0].url == "https://example.com/gpt5"


def test_fetch_single_handles_missing_fields():
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = [
        _make_entry(title="No Link News")
    ]
    with patch("feedparser.parse", return_value=mock_feed):
        items = fetch_single("TestSource", "https://example.com/rss", timeout=10)
        assert len(items) == 1
        assert items[0].url == ""
        assert items[0].summary == ""


def test_fetch_single_handles_exception():
    with patch("feedparser.parse", side_effect=Exception("Connection refused")):
        items = fetch_single("BadSource", "https://bad.example.com/rss", timeout=10)
        assert items == []


def test_fetch_single_bozo_no_entries():
    """Bozo detected and no entries: should return empty."""
    mock_feed = MagicMock()
    mock_feed.bozo = True
    mock_feed.bozo_exception = Exception("Malformed XML")
    mock_feed.entries = []
    with patch("feedparser.parse", return_value=mock_feed):
        items = fetch_single("BadFeed", "https://bad.example.com/rss", timeout=10)
        assert items == []


def test_fetch_all_aggregates_sources(monkeypatch):
    """fetch_all should collect items from multiple sources."""
    sources = [
        {"name": "SourceA", "url": "https://a.example.com/rss"},
        {"name": "SourceB", "url": "https://b.example.com/rss"},
    ]

    def mock_fetch(name, url, timeout):
        if name == "SourceA":
            return [
                NewsItem("News A", "http://a.com/1", "", name, now())
            ]
        return []

    monkeypatch.setattr(
        "src.fetcher.rss_fetcher.fetch_single", mock_fetch
    )
    items = fetch_all(sources)
    assert len(items) == 1
    assert items[0].title == "News A"
