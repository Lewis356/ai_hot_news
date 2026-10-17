"""Daily digest pipeline orchestrator with explicit run outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger

from src.evaluator import EvaluationResult, evaluate_news
from src.fetcher.rss_fetcher import FetchBatch, fetch_all_with_report
from src.models import EvaluatedItem, NewsItem
from src.observability import Metrics, emit_run_summary, step_timer
from src.processor.dedup import deduplicate
from src.processor.filter import filter_recent
from src.publisher.card_builder import build_card
from src.publisher.feishu import PublishResult, PublishStatus, send_card
from src.utils.redact import redact


class DigestStatus(str, Enum):
    SENT = "sent"
    EMPTY_SENT = "empty_sent"
    DRY_RUN = "dry_run"
    FETCH_FAILED = "fetch_failed"
    EVALUATION_FAILED = "evaluation_failed"
    PUBLISH_FAILED = "publish_failed"


@dataclass(frozen=True)
class DigestResult:
    status: DigestStatus
    metrics: Metrics
    failure_reason: str | None = None

    @property
    def provider_requested(self) -> str:
        return self.metrics.provider_requested

    @property
    def provider_used(self) -> str:
        return self.metrics.provider_used

    @property
    def fallback_used(self) -> bool:
        return self.metrics.fallback_used

    @property
    def exit_code(self) -> int:
        return 0 if self.status in {
            DigestStatus.SENT,
            DigestStatus.EMPTY_SENT,
            DigestStatus.DRY_RUN,
        } else 1


def step_fetch(config, metrics: Metrics) -> FetchBatch:
    """Fetch all configured sources and record each source outcome."""
    with step_timer(metrics, "fetch"):
        batch = fetch_all_with_report(config.rss_sources)
    metrics.fetched = len(batch.items)
    metrics.source_reports = batch.reports
    metrics.failed_sources = [source.name for source in batch.sources if not source.ok]
    metrics.degraded = any(source.status != "ok" for source in batch.sources)
    return batch


def step_dedup(items: list[NewsItem], config, metrics: Metrics) -> list[NewsItem]:
    """Remove URL and title duplicates."""
    threshold = config.dedup.get("title_similarity_threshold", 0.80)
    with step_timer(metrics, "dedup"):
        result = deduplicate(items, threshold)
    metrics.deduped = len(result)
    return result


def step_filter(
    items: list[NewsItem],
    metrics: Metrics,
    *,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Keep dated items from the last 24 hours."""
    metrics.dropped_undated = sum(item.published_at is None for item in items)
    with step_timer(metrics, "filter"):
        result = filter_recent(items, hours=24, now=now)
    metrics.recent = len(result)
    return result


def step_evaluate(
    items: list[NewsItem], config, metrics: Metrics
) -> EvaluationResult:
    """Evaluate candidates and record the provider that actually produced them."""
    with step_timer(metrics, "evaluate"):
        result = evaluate_news(items, config)
    metrics.evaluated = len(result.items)
    metrics.provider_requested = result.requested_provider
    metrics.provider_used = result.used_provider
    metrics.fallback_used = result.fallback_used
    metrics.fallback_reason = result.fallback_reason
    metrics.degraded = metrics.degraded or result.fallback_used
    return result


def _build_digest_card(
    evaluated: list[EvaluatedItem],
    now: datetime,
    metrics: Metrics,
) -> dict:
    return build_card(
        evaluated,
        now,
        provider=metrics.provider_used or metrics.provider_requested,
        pipeline_counts={
            "fetched": metrics.fetched,
            "deduped": metrics.deduped,
            "recent": metrics.recent,
            "evaluated": metrics.evaluated,
        },
        digest_id=metrics.digest_id,
    )


def step_publish(
    evaluated: list[EvaluatedItem],
    config,
    now: datetime,
    metrics: Metrics,
) -> PublishResult:
    """Build and send one Feishu card."""
    with step_timer(metrics, "publish"):
        result = send_card(_build_digest_card(evaluated, now, metrics), config)
    metrics.publish_outcome = result.status.value
    return result


def _finish(
    status: DigestStatus,
    metrics: Metrics,
    failure_reason: str | None = None,
) -> DigestResult:
    metrics.status = status.value
    metrics.failure_reason = redact(failure_reason)[:200] if failure_reason else None
    emit_run_summary(metrics)
    return DigestResult(
        status=status,
        metrics=metrics,
        failure_reason=metrics.failure_reason,
    )


def _deliver(
    evaluated: list[EvaluatedItem],
    config,
    now: datetime,
    metrics: Metrics,
    *,
    empty: bool,
    dry_run: bool,
) -> DigestResult:
    if dry_run:
        with step_timer(metrics, "publish"):
            _build_digest_card(evaluated, now, metrics)
        metrics.publish_outcome = "skipped"
        return _finish(DigestStatus.DRY_RUN, metrics)

    publication = step_publish(evaluated, config, now, metrics)
    if publication.status is PublishStatus.SENT:
        status = DigestStatus.EMPTY_SENT if empty else DigestStatus.SENT
        return _finish(status, metrics)
    return _finish(
        DigestStatus.PUBLISH_FAILED,
        metrics,
        publication.error or f"Feishu delivery status: {publication.status.value}",
    )


def run_daily_digest(
    config,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> DigestResult:
    """Execute one digest run and return a process-friendly outcome."""
    timezone_name = config.schedule.get("timezone", "Asia/Shanghai")
    local_timezone = ZoneInfo(timezone_name)
    run_time = now.astimezone(local_timezone) if now else datetime.now(local_timezone)
    metrics = Metrics(
        run_id=uuid4().hex,
        digest_id=f"ai-news-{run_time:%Y-%m-%d}",
        provider_requested=config.ai.get("provider", "deepseek"),
    )

    batch = step_fetch(config, metrics)
    if not batch.sources or not any(source.ok for source in batch.sources):
        logger.error("Every RSS source failed; digest was not published")
        return _finish(
            DigestStatus.FETCH_FAILED,
            metrics,
            "Every RSS source failed",
        )

    if not batch.items:
        if metrics.failed_sources:
            logger.error("Some RSS sources failed, so an empty digest cannot be trusted")
            return _finish(
                DigestStatus.FETCH_FAILED,
                metrics,
                "No items were fetched and some RSS sources failed",
            )
        logger.info("RSS fetch succeeded but returned no items; publishing an empty card")
        return _deliver([], config, run_time, metrics, empty=True, dry_run=dry_run)

    items = step_filter(batch.items, metrics, now=run_time)
    if not items:
        if metrics.failed_sources:
            logger.error("Some RSS sources failed, so an empty digest cannot be trusted")
            return _finish(
                DigestStatus.FETCH_FAILED,
                metrics,
                "No recent items and some RSS sources failed",
            )
        logger.info("No dated news was published in the last 24 hours")
        return _deliver([], config, run_time, metrics, empty=True, dry_run=dry_run)
    items = step_dedup(items, config, metrics)

    try:
        evaluation = step_evaluate(items, config, metrics)
    except Exception as exc:  # rule provider failures still need a clean exit code
        reason = redact(f"{type(exc).__name__}: {exc}")[:200]
        logger.error(redact(f"News evaluation failed: {exc}"))
        return _finish(DigestStatus.EVALUATION_FAILED, metrics, reason)

    if not evaluation.items:
        return _finish(
            DigestStatus.EVALUATION_FAILED,
            metrics,
            evaluation.fallback_reason or "Evaluation returned no items",
        )

    return _deliver(
        evaluation.items,
        config,
        run_time,
        metrics,
        empty=False,
        dry_run=dry_run,
    )
