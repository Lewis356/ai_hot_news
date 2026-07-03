from datetime import datetime, timezone
from src.models import NewsItem, EvaluatedItem


def test_news_item_creation():
    now = datetime.now(timezone.utc)
    item = NewsItem(
        title="Test News",
        url="https://example.com/news/1",
        summary="A test summary",
        source="TestSource",
        published_at=now,
    )
    assert item.title == "Test News"
    assert item.url == "https://example.com/news/1"
    assert item.source == "TestSource"
    assert item.fetched_at is not None
    assert item.published_at == now


def test_evaluated_item_creation():
    now = datetime.now(timezone.utc)
    item = EvaluatedItem(
        title="Test News",
        url="https://example.com/news/1",
        source="TestSource",
        chinese_summary="这是一条测试新闻摘要，涉及AI技术进展。",
        importance=8,
        keywords=["测试", "AI"],
        published_at=now,
    )
    assert item.importance == 8
    assert len(item.keywords) == 2
    assert "测试" in item.keywords
    assert "AI" in item.keywords
