"""Daily digest pipeline orchestrator.

Split into discrete, individually-testable steps. Each step writes its
duration into the shared :class:`Metrics` so the end-of-run ``METRICS``
line gives an operator everything they need to debug.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from src.evaluator import evaluate_news
from src.fetcher.rss_fetcher import fetch_all_with_report
from src.models import EvaluatedItem, NewsItem
from src.observability import Metrics, emit_metrics, step_timer
from src.processor.dedup import deduplicate
from src.processor.filter import filter_recent
from src.publisher.card_builder import build_card
from src.publisher.feishu import send_card


# ---------------------------------------------------------------------------
# Pipeline steps (each testable in isolation)
# ---------------------------------------------------------------------------
def step_fetch(config, metrics: Metrics) -> list[NewsItem]:
    """Fetch RSS feeds concurrently and record per-source reports."""
    with step_timer(metrics, "fetch"):
        items, report = fetch_all_with_report(config.rss_sources)
    metrics.fetched = len(items)
    metrics.source_reports = report
    return items


def step_dedup(items: list[NewsItem], config, metrics: Metrics) -> list[NewsItem]:
    """Remove URL / title duplicates."""
    threshold = config.dedup.get("title_similarity_threshold", 0.80)
    with step_timer(metrics, "dedup"):
        items = deduplicate(items, threshold)
    metrics.deduped = len(items)
    return items


def step_filter(items: list[NewsItem], metrics: Metrics) -> list[NewsItem]:
    """Keep only the last 24h (per the platform default)."""
    with step_timer(metrics, "filter"):
        items = filter_recent(items, hours=24)
    metrics.recent = len(items)
    return items


def step_evaluate(items: list[NewsItem], config, metrics: Metrics) -> list[EvaluatedItem]:
    """Run the configured AI evaluator (with rule-based fallback)."""
    metrics.provider = config.ai.get("provider", "deepseek")
    with step_timer(metrics, "evaluate"):
        evaluated = evaluate_news(items, config)
    metrics.evaluated = len(evaluated)
    return evaluated


def step_publish(
    evaluated: list[EvaluatedItem],
    config,
    now: datetime,
    metrics: Metrics,
) -> bool:
    """Build the Feishu card and POST it (HMAC-signed if secret set)."""
    with step_timer(metrics, "publish"):
        card = build_card(
            evaluated,
            now,
            provider=metrics.provider,
            pipeline_counts={
                "fetched": metrics.fetched,
                "deduped": metrics.deduped,
                "recent": metrics.recent,
                "evaluated": metrics.evaluated,
            },
        )
        success = send_card(card, config)
    return success


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_daily_digest(config) -> None:
    """Execute the full daily digest pipeline (used by ``main`` and ``run_once``)."""
    logger.info("=" * 50)
    logger.info("Starting daily AI news digest pipeline")
    now = datetime.now(timezone.utc)
    metrics = Metrics()

    items = step_fetch(config, metrics)
    if not items:
        logger.error("No items fetched from any source. Aborting.")
        emit_metrics(metrics)
        return

    items = step_dedup(items, config, metrics)

    items = step_filter(items, metrics)
    if not items:
        logger.info("No recent news after filtering. Skipping digest.")
        emit_metrics(metrics)
        return

    evaluated = step_evaluate(items, config, metrics)
    if not evaluated:
        logger.error("AI evaluation returned no results. Aborting.")
        emit_metrics(metrics)
        return

    success = step_publish(evaluated, config, now, metrics)

    emit_metrics(metrics)

    if success:
        logger.info(
            f"Daily digest completed. {len(evaluated)} items published."
        )
    else:
        logger.error("Daily digest completed but Feishu send failed.")

    logger.info("=" * 50)