from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from src.fetcher.rss_fetcher import fetch_all, fetch_all_with_report, fetch_single


def _make_entry(
    title="", link="", summary="", published_parsed=None, updated_parsed=None, entry_id=None
):
    """Create a feedparser-like entry with attribute access."""
    return SimpleNamespace(
        title=title,
        link=link,
        summary=summary,
        published_parsed=published_parsed,
        updated_parsed=updated_parsed,
        id=entry_id,
    )


def _mock_response(text="<rss />"):
    response = MagicMock()
    response.text = text
    response.raise_for_status.return_value = None
    return response


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
    with patch("httpx.get", return_value=_mock_response()), patch(
        "feedparser.parse", return_value=mock_feed
    ):
        result = fetch_single("TestSource", "https://example.com/rss", timeout=10)
        items = result.items
        assert result.status == "ok"
        assert len(items) == 1
        assert items[0].title == "GPT-5 Announced"
        assert items[0].source == "TestSource"
        assert items[0].url == "https://example.com/gpt5"
        assert items[0].item_id


def test_fetcher_uses_entry_guid_for_stable_identity():
    feed = SimpleNamespace(
        bozo=False,
        entries=[
            _make_entry(
                title="First title",
                link="https://example.com/one",
                entry_id="stable-guid",
            ),
            _make_entry(
                title="Changed title",
                link="https://example.com/two",
                entry_id="stable-guid",
            ),
        ],
    )

    with patch("httpx.get", return_value=_mock_response()), patch(
        "feedparser.parse", return_value=feed
    ):
        items = fetch_single("Source", "https://example.com/rss").items

    assert items[0].item_id == items[1].item_id


def test_fetch_single_handles_missing_fields():
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = [
        _make_entry(title="No Link News")
    ]
    with patch("httpx.get", return_value=_mock_response()), patch(
        "feedparser.parse", return_value=mock_feed
    ):
        result = fetch_single("TestSource", "https://example.com/rss", timeout=10)
        items = result.items
        assert result.status == "ok"
        assert len(items) == 1
        assert items[0].url == ""
        assert items[0].summary == ""


def test_fetch_single_handles_exception():
    with patch("httpx.get", return_value=_mock_response()), patch(
        "feedparser.parse", side_effect=Exception("Parser crashed")
    ):
        result = fetch_single("BadSource", "https://bad.example.com/rss", timeout=10)
        assert result.items == []
        assert result.status == "parse_error"


def test_fetch_single_bozo_no_entries():
    """Bozo detected and no entries: should return empty."""
    mock_feed = MagicMock()
    mock_feed.bozo = True
    mock_feed.bozo_exception = Exception("Malformed XML")
    mock_feed.entries = []
    with patch("httpx.get", return_value=_mock_response()), patch(
        "feedparser.parse", return_value=mock_feed
    ):
        result = fetch_single("BadFeed", "https://bad.example.com/rss", timeout=10)
        assert result.items == []
        assert result.status == "parse_error"


def test_fetch_all_aggregates_sources(monkeypatch):
    """fetch_all should collect items from multiple sources."""
    sources = [
        {"name": "SourceA", "url": "https://a.example.com/rss"},
        {"name": "SourceB", "url": "https://b.example.com/rss"},
    ]

    def request(url, **kwargs):
        return _mock_response(url)

    def parse(text):
        entries = (
            [
                _make_entry(
                    "News A",
                    "http://a.com/1",
                    published_parsed=(2026, 10, 16, 0, 0, 0, 0, 0, 0),
                )
            ]
            if text == sources[0]["url"]
            else []
        )
        return SimpleNamespace(bozo=False, entries=entries)

    monkeypatch.setattr("src.fetcher.rss_fetcher.httpx.get", request)
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", parse)
    items = fetch_all(sources)
    assert len(items) == 1
    assert items[0].title == "News A"


def test_fetch_all_reports_http_error(monkeypatch):
    """A failed HTTP request must not be reported as a successful empty feed."""
    sources = [{"name": "Offline", "url": "https://offline.example.com/rss"}]

    def fail_request(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr("src.fetcher.rss_fetcher.httpx.get", fail_request)

    batch = fetch_all_with_report(sources)

    assert batch.items == []
    assert len(batch.sources) == 1
    result = batch.sources[0]
    assert result.name == "Offline"
    assert result.status == "http_error"
    assert result.ok is False
    assert result.error == "Connection refused"


def test_fetch_all_reports_parse_error_when_feed_has_no_usable_entries(monkeypatch):
    """Malformed XML with no entries is a failure, not a successful empty feed."""
    sources = [{"name": "Malformed", "url": "https://example.com/rss"}]
    feed = SimpleNamespace(
        bozo=True,
        bozo_exception=ValueError("Malformed XML"),
        entries=[],
    )
    monkeypatch.setattr(
        "src.fetcher.rss_fetcher.httpx.get", lambda *args, **kwargs: _mock_response()
    )
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", lambda text: feed)

    batch = fetch_all_with_report(sources)

    result = batch.sources[0]
    assert result.status == "parse_error"
    assert result.ok is False
    assert result.error == "Malformed XML"


def test_fetch_all_reports_parse_warning_when_entries_are_usable(monkeypatch):
    """A recoverable parser warning remains a partial success with its items."""
    sources = [{"name": "Recoverable", "url": "https://example.com/rss"}]
    feed = SimpleNamespace(
        bozo=True,
        bozo_exception=ValueError("Invalid character"),
        entries=[_make_entry(title="Usable", link="https://example.com/usable")],
    )
    monkeypatch.setattr(
        "src.fetcher.rss_fetcher.httpx.get", lambda *args, **kwargs: _mock_response()
    )
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", lambda text: feed)

    batch = fetch_all_with_report(sources)

    result = batch.sources[0]
    assert result.status == "parse_warning"
    assert result.ok is True
    assert result.error == "Invalid character"
    assert [item.title for item in result.items] == ["Usable"]


def test_fetch_all_reports_parser_exception(monkeypatch):
    """A parser exception remains visible as a per-source parse error."""
    sources = [{"name": "BrokenParser", "url": "https://example.com/rss"}]
    monkeypatch.setattr(
        "src.fetcher.rss_fetcher.httpx.get", lambda *args, **kwargs: _mock_response()
    )

    def fail_parse(text):
        raise ValueError("Parser crashed")

    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", fail_parse)

    batch = fetch_all_with_report(sources)

    assert len(batch.sources) == 1
    result = batch.sources[0]
    assert result.status == "parse_error"
    assert result.ok is False
    assert result.error == "Parser crashed"


def test_fetch_all_uses_updated_date_then_none_when_published_date_is_missing(
    monkeypatch,
):
    """Dates use published, then updated; an unknown date stays unknown."""
    sources = [{"name": "Dates", "url": "https://example.com/rss"}]
    feed = SimpleNamespace(
        bozo=False,
        entries=[
            _make_entry(
                title="Published",
                published_parsed=(2026, 10, 16, 1, 2, 3, 0, 0, 0),
                updated_parsed=(2026, 10, 15, 1, 2, 3, 0, 0, 0),
            ),
            _make_entry(
                title="Updated",
                published_parsed=(2026, 13, 14, 4, 5, 6, 0, 0, 0),
                updated_parsed=(2026, 10, 14, 4, 5, 6, 0, 0, 0),
            ),
            _make_entry(title="Unknown"),
        ],
    )
    monkeypatch.setattr(
        "src.fetcher.rss_fetcher.httpx.get", lambda *args, **kwargs: _mock_response()
    )
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", lambda text: feed)

    batch = fetch_all_with_report(sources)

    dates = {item.title: item.published_at for item in batch.items}
    assert dates == {
        "Published": datetime(2026, 10, 16, 1, 2, 3, tzinfo=timezone.utc),
        "Updated": datetime(2026, 10, 14, 4, 5, 6, tzinfo=timezone.utc),
        "Unknown": None,
    }


def test_fetch_all_orders_each_source_newest_first_then_round_robins(monkeypatch):
    """Slow sources retain config priority and no source monopolizes the batch."""
    sources = [
        {"name": "SourceA", "url": "https://a.example.com/rss"},
        {"name": "SourceB", "url": "https://b.example.com/rss"},
    ]
    entries_by_url = {
        sources[0]["url"]: [
            _make_entry(
                title="A-old",
                published_parsed=(2026, 10, 14, 0, 0, 0, 0, 0, 0),
            ),
            _make_entry(
                title="A-new",
                published_parsed=(2026, 10, 16, 0, 0, 0, 0, 0, 0),
            ),
        ],
        sources[1]["url"]: [
            _make_entry(
                title="B-old",
                published_parsed=(2026, 10, 13, 0, 0, 0, 0, 0, 0),
            ),
            _make_entry(
                title="B-new",
                published_parsed=(2026, 10, 15, 0, 0, 0, 0, 0, 0),
            ),
        ],
    }
    source_b_started = Event()

    def request(url, **kwargs):
        if url == sources[0]["url"]:
            assert source_b_started.wait(timeout=1)
        else:
            source_b_started.set()
        return _mock_response(url)

    def parse(text):
        return SimpleNamespace(bozo=False, entries=entries_by_url[text])

    monkeypatch.setattr("src.fetcher.rss_fetcher.httpx.get", request)
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", parse)

    batch = fetch_all_with_report(sources)

    assert [result.name for result in batch.sources] == ["SourceA", "SourceB"]
    assert [[item.title for item in result.items] for result in batch.sources] == [
        ["A-new", "A-old"],
        ["B-new", "B-old"],
    ]
    assert [item.title for item in batch.items] == [
        "A-new",
        "B-new",
        "A-old",
        "B-old",
    ]


def test_fetch_all_preserves_partial_success_and_every_source_result(monkeypatch):
    """One failed source does not discard items or the report from another source."""
    sources = [
        {"name": "Online", "url": "https://online.example.com/rss"},
        {"name": "Offline", "url": "https://offline.example.com/rss"},
    ]

    def request(url, **kwargs):
        if url == sources[1]["url"]:
            raise httpx.ConnectError("Connection refused")
        return _mock_response()

    feed = SimpleNamespace(
        bozo=False,
        entries=[
            _make_entry(
                title="Available",
                published_parsed=(2026, 10, 16, 0, 0, 0, 0, 0, 0),
            )
        ],
    )
    monkeypatch.setattr("src.fetcher.rss_fetcher.httpx.get", request)
    monkeypatch.setattr("src.fetcher.rss_fetcher.feedparser.parse", lambda text: feed)

    batch = fetch_all_with_report(sources)

    assert [item.title for item in batch.items] == ["Available"]
    assert [(result.name, result.status) for result in batch.sources] == [
        ("Online", "ok"),
        ("Offline", "http_error"),
    ]
