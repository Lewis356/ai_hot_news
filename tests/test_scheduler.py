"""Tests for the daily digest orchestration contract."""
from datetime import datetime, timezone
from unittest.mock import patch

from src.config import Config
from src.evaluator import EvaluationResult
from src.fetcher.rss_fetcher import FetchBatch, SourceFetchResult
from src.models import EvaluatedItem, NewsItem
from src.observability import Metrics
from src.publisher.feishu import PublishResult, PublishStatus
from src.scheduler import (
    DigestStatus,
    run_daily_digest,
    step_dedup,
    step_evaluate,
    step_fetch,
    step_filter,
    step_publish,
)

NOW = datetime(2026, 10, 17, 0, 7, tzinfo=timezone.utc)


def make_config() -> Config:
    return Config(
        deepseek_api_key="sk-test",
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        feishu_webhook_secret="secret",
        rss_sources=[{"name": "Test", "url": "https://test.example/feed"}],
        schedule={"timezone": "Asia/Shanghai"},
        ai={"provider": "rule", "top_n": 5, "max_candidates": 50},
        dedup={"title_similarity_threshold": 0.80},
    )


def make_news_item(title: str, source: str = "test") -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.com/{title}",
        summary=f"summary of {title}",
        source=source,
        published_at=NOW,
    )


def make_eval_item(title: str, importance: int = 8) -> EvaluatedItem:
    return EvaluatedItem(
        title=title,
        url=f"https://example.com/{title}",
        source="test",
        chinese_summary=f"摘要 {title}",
        importance=importance,
        keywords=["AI"],
        published_at=NOW,
    )


def make_batch(
    items: list[NewsItem], *, status: str = "ok", name: str = "Test"
) -> FetchBatch:
    return FetchBatch(
        items=items,
        sources=[SourceFetchResult(name=name, status=status, items=items)],
    )


def test_step_fetch_records_metrics():
    metrics = Metrics()
    batch = make_batch([make_news_item("A"), make_news_item("B")])

    with patch("src.scheduler.fetch_all_with_report", return_value=batch):
        result = step_fetch(make_config(), metrics)

    assert result is batch
    assert metrics.fetched == 2
    assert metrics.source_reports["Test"]["status"] == "ok"
    assert metrics.failed_sources == []
    assert "fetch" in metrics.duration_ms


def test_step_dedup_drops_duplicates():
    items = [
        make_news_item("Same title"),
        make_news_item("Same title"),
        make_news_item("Different title"),
    ]
    metrics = Metrics()

    out = step_dedup(items, make_config(), metrics)

    assert len(out) == 2
    assert metrics.deduped == 2


def test_step_filter_counts_undated_items():
    metrics = Metrics()
    undated = make_news_item("No date")
    undated.published_at = None

    out = step_filter([make_news_item("A"), undated], metrics, now=NOW)

    assert len(out) == 1
    assert metrics.recent == 1
    assert metrics.dropped_undated == 1


def test_step_evaluate_records_actual_provider():
    metrics = Metrics()
    evaluated = [make_eval_item("A")]
    evaluation = EvaluationResult(
        evaluated, "deepseek", "rule", True, "primary provider returned no items"
    )

    with patch("src.scheduler.evaluate_news", return_value=evaluation):
        result = step_evaluate([make_news_item("A")], make_config(), metrics)

    assert result is evaluation
    assert metrics.evaluated == 1
    assert metrics.provider_requested == "deepseek"
    assert metrics.provider_used == "rule"
    assert metrics.fallback_used is True
    assert metrics.fallback_reason == "primary provider returned no items"


def test_step_publish_builds_card_and_posts():
    metrics = Metrics(fetched=10, deduped=8, recent=5, evaluated=1)
    metrics.provider_used = "rule"
    sent = PublishResult(PublishStatus.SENT)

    with patch("src.scheduler.send_card", return_value=sent) as mock_send:
        result = step_publish(
            [make_eval_item("A", importance=9)], make_config(), NOW, metrics
        )

    assert result is sent
    assert "抓取 10" in str(mock_send.call_args.args[0])
    assert "入选 1" in str(mock_send.call_args.args[0])
    assert "publish" in metrics.duration_ms


def test_run_daily_digest_succeeds_with_partial_source_failure():
    items = [make_news_item("A")]
    batch = FetchBatch(
        items=items,
        sources=[
            SourceFetchResult("Online", "ok", items=items),
            SourceFetchResult("Offline", "http_error", error="timeout"),
        ],
    )

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card",
        return_value=PublishResult(PublishStatus.SENT),
    ):
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.SENT
    assert result.exit_code == 0
    assert result.metrics.degraded is True
    assert result.metrics.failed_sources == ["Offline"]
    assert result.provider_used == "rule"


def test_run_filters_before_fuzzy_deduplication():
    items = [make_news_item("A"), make_news_item("B")]
    call_order: list[str] = []

    def filter_first(candidates, hours, *, now):
        call_order.append("filter")
        return candidates[:1]

    def dedup_second(candidates, threshold):
        call_order.append("dedup")
        return candidates

    with patch("src.scheduler.fetch_all_with_report", return_value=make_batch(items)), patch(
        "src.scheduler.filter_recent", side_effect=filter_first
    ), patch("src.scheduler.deduplicate", side_effect=dedup_second), patch(
        "src.scheduler.send_card", return_value=PublishResult(PublishStatus.SENT)
    ):
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.SENT
    assert call_order == ["filter", "dedup"]


def test_run_daily_digest_fails_when_every_source_fails():
    batch = FetchBatch(
        sources=[SourceFetchResult("Offline", "http_error", error="timeout")]
    )

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card"
    ) as mock_send:
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.FETCH_FAILED
    assert result.exit_code == 1
    assert result.metrics.status == "fetch_failed"
    mock_send.assert_not_called()


def test_run_daily_digest_sends_empty_card_after_successful_empty_fetch():
    batch = make_batch([])

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card",
        return_value=PublishResult(PublishStatus.SENT),
    ) as mock_send:
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.EMPTY_SENT
    assert result.exit_code == 0
    assert "暂无更新" in str(mock_send.call_args.args[0])


def test_run_daily_digest_does_not_claim_empty_when_another_source_failed():
    batch = FetchBatch(
        sources=[
            SourceFetchResult("Empty", "ok"),
            SourceFetchResult("Offline", "http_error", error="timeout"),
        ]
    )

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card"
    ) as mock_send:
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.FETCH_FAILED
    assert result.exit_code == 1
    mock_send.assert_not_called()


def test_run_daily_digest_does_not_claim_empty_after_filter_when_source_failed():
    old_item = make_news_item("Old")
    old_item.published_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
    batch = FetchBatch(
        items=[old_item],
        sources=[
            SourceFetchResult("Stale", "ok", items=[old_item]),
            SourceFetchResult("Offline", "http_error", error="timeout"),
        ],
    )

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card"
    ) as mock_send:
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.FETCH_FAILED
    assert result.metrics.failure_reason == "No recent items and some RSS sources failed"
    mock_send.assert_not_called()


def test_run_daily_digest_dry_run_never_publishes():
    batch = make_batch([make_news_item("A")])

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card"
    ) as mock_send:
        result = run_daily_digest(make_config(), dry_run=True, now=NOW)

    assert result.status is DigestStatus.DRY_RUN
    assert result.exit_code == 0
    assert result.metrics.publish_outcome == "skipped"
    mock_send.assert_not_called()


def test_run_daily_digest_publish_unknown_is_a_failure():
    batch = make_batch([make_news_item("A")])

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card",
        return_value=PublishResult(PublishStatus.UNKNOWN, "read timeout"),
    ):
        result = run_daily_digest(make_config(), now=NOW)

    assert result.status is DigestStatus.PUBLISH_FAILED
    assert result.exit_code == 1
    assert result.metrics.publish_outcome == "unknown"
    assert result.failure_reason == "read timeout"
    assert result.metrics.failure_reason == "read timeout"


def test_run_summary_has_stable_digest_id_and_unique_run_id():
    batch = make_batch([make_news_item("A")])

    with patch("src.scheduler.fetch_all_with_report", return_value=batch), patch(
        "src.scheduler.send_card", return_value=PublishResult(PublishStatus.SENT)
    ):
        first = run_daily_digest(make_config(), now=NOW)
        second = run_daily_digest(make_config(), now=NOW)

    assert first.metrics.digest_id == "ai-news-2026-10-17"
    assert first.metrics.run_id
    assert first.metrics.run_id != second.metrics.run_id
