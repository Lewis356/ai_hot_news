"""Lightweight step timing + metrics for the daily digest pipeline.

The intent is *deliberately* small: a context manager that times a stage
and a dataclass that aggregates counts so we can emit a single
``RUN_SUMMARY {...}`` log line at the end. No external dep, no Prometheus.
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from loguru import logger


@dataclass
class Metrics:
    """Per-run counters and per-step durations.

    ``source_reports`` mirrors the per-source dict emitted by
    :func:`src.fetcher.rss_fetcher.fetch_all_with_report` so an operator
    can see which RSS feeds failed silently.
    """

    run_id: str = ""
    digest_id: str = ""
    fetched: int = 0
    deduped: int = 0
    recent: int = 0
    evaluated: int = 0
    dropped_undated: int = 0
    duration_ms: dict[str, int] = field(default_factory=dict)
    source_reports: dict[str, dict] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    provider_requested: str = ""
    provider_used: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    publish_outcome: str = "not_attempted"
    status: str = "running"
    failure_reason: str | None = None
    degraded: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@contextmanager
def step_timer(metrics: Metrics, name: str) -> Iterator[None]:
    """Time a code block and record ``metrics.duration_ms[name]``."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        metrics.duration_ms[name] = elapsed_ms
        logger.debug(f"step '{name}' took {elapsed_ms} ms")


def emit_run_summary(metrics: Metrics) -> None:
    """Emit the only structured end-of-run summary line."""
    logger.info(f"RUN_SUMMARY {metrics.to_json()}")


__all__ = ["Metrics", "step_timer", "emit_run_summary"]
