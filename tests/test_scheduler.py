"""Tests for the split scheduler pipeline + METRICS line."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.models import EvaluatedItem, NewsItem
from src.observability import Metrics
from src.scheduler import (
    run_daily_digest,
    step_dedup,
    step_evaluate,
    step_fetch,
    step_filter,
    step_publish,
)


def make_config() -> Config:
    return Config(
        deepseek_api_key="sk-test",
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        feishu_webhook_secret="",
        rss_sources=[{"name": "Test", "url": "https://test.example/feed"}],
        ai={"provider": "rule", "top_n": 5, "max_candidates": 50},
        dedup={"title_similarity_threshold": 0.80},
    )


def make_news_item(title: str, source: str = "test") -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        summary=f"summary of {title}",
        source=source,
        published_at=datetime.now(timezone.utc),
    )


def make_eval_item(title: str, importance: int = 8) -> EvaluatedItem:
    return EvaluatedItem(
        title=title,
        url=f"https://example.com/{title}",
        source="test",
        chinese_summary=f"摘要 {title}",
        importance=importance,
        keywords=["AI"],
        published_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Step-level tests
# ---------------------------------------------------------------------------
def test_step_fetch_records_metrics():
    config = make_config()
    metrics = Metrics()
    with patch(
        "src.scheduler.fetch_all_with_report",
        return_value=([make_news_item("A"), make_news_item("B")],
                       {"Test": {"ok": True, "count": 2, "error": None, "duration_ms": 10}}),
    ):
        items = step_fetch(config, metrics)
    assert metrics.fetched == 2
    assert metrics.source_reports["Test"]["ok"] is True
    assert "fetch" in metrics.duration_ms
    assert len(items) == 2


def test_step_dedup_drops_duplicates():
    items = [make_news_item("Same title"), make_news_item("Same title"),
             make_news_item("Different title")]
    metrics = Metrics()
    out = step_dedup(items, make_config(), metrics)
    assert len(out) == 2
    assert metrics.deduped == 2


def test_step_filter_keeps_recent():
    metrics = Metrics()
    out = step_filter([make_news_item("A")], metrics)
    assert len(out) == 1
    assert metrics.recent == 1


def test_step_evaluate_uses_rule_provider():
    config = make_config()
    metrics = Metrics()
    items = [make_news_item("GPT-5 发布"), make_news_item("开源进展")]
    out = step_evaluate(items, config, metrics)
    assert metrics.provider == "rule"
    assert metrics.evaluated > 0
    assert all(isinstance(e, EvaluatedItem) for e in out)


def test_step_publish_builds_card_and_posts():
    config = make_config()
    metrics = Metrics()
    metrics.fetched = 10
    metrics.deduped = 8
    metrics.recent = 5
    metrics.evaluated = 3
    items = [make_eval_item("A", importance=9)]

    with patch("src.scheduler.send_card", return_value=True) as mock_send:
        ok = step_publish(items, config, datetime.now(timezone.utc), metrics)
    assert ok is True
    assert mock_send.call_count == 1
    sent_card = mock_send.call_args.args[0]
    # Pipeline counts should be embedded in the card
    assert "抓取 10" in str(sent_card)
    assert "入选 3" in str(sent_card)
    assert "publish" in metrics.duration_ms


# ---------------------------------------------------------------------------
# End-to-end run with mocks
# ---------------------------------------------------------------------------
def test_run_daily_digest_emits_metrics_line(caplog):
    """Full pipeline with all I/O mocked — should end with METRICS log line."""
    config = make_config()
    items = [make_news_item("A"), make_news_item("B")]
    evaluated = [make_eval_item("A"), make_eval_item("B")]

    with patch("src.scheduler.fetch_all_with_report",
               return_value=(items, {"Test": {"ok": True, "count": 2, "error": None, "duration_ms": 5}})), \
         patch("src.scheduler.evaluate_news", return_value=evaluated), \
         patch("src.scheduler.send_card", return_value=True):
        run_daily_digest(config)

    # At least one METRICS line should have been emitted
    metrics_lines = [r.message for r in caplog.records if "METRICS" in r.message]
    assert metrics_lines, "expected METRICS log line"
    assert '"fetched": 2' in metrics_lines[-1]
    assert '"evaluated": 2' in metrics_lines[-1]
    assert '"deduped"' in metrics_lines[-1]
    assert '"duration_ms"' in metrics_lines[-1]


def test_run_daily_digest_aborts_when_no_items(caplog):
    config = make_config()
    with patch("src.scheduler.fetch_all_with_report", return_value=([], {})):
        run_daily_digest(config)
    metrics_lines = [r.message for r in caplog.records if "METRICS" in r.message]
    assert metrics_lines
    assert '"fetched": 0' in metrics_lines[-1]


def test_run_daily_digest_aborts_when_no_recent(caplog):
    config = make_config()
    items = [make_news_item("A")]
    with patch("src.scheduler.fetch_all_with_report",
               return_value=(items, {"Test": {"ok": True, "count": 1, "error": None, "duration_ms": 5}})):
        run_daily_digest(config)
    metrics_lines = [r.message for r in caplog.records if "METRICS" in r.message]
    assert metrics_lines
    assert '"fetched": 1' in metrics_lines[-1]
    # We expect recent==0 since fetch was mocked but filter would drop
    assert '"recent": 0' in metrics_lines[-1]