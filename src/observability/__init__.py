"""Lightweight step timing + metrics for the daily digest pipeline.

The intent is *deliberately* small: a context manager that times a stage
and a dataclass that aggregates counts so we can emit a single
``METRICS {...}`` log line at the end. No external dep, no Prometheus.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Iterator

from loguru import logger


@dataclass
class Metrics:
    """Per-run counters and per-step durations.

    ``source_reports`` mirrors the per-source dict emitted by
    :func:`src.fetcher.rss_fetcher.fetch_all_with_report` so an operator
    can see which RSS feeds failed silently.
    """

    fetched: int = 0
    deduped: int = 0
    recent: int = 0
    evaluated: int = 0
    duration_ms: dict[str, int] = field(default_factory=dict)
    source_reports: dict[str, dict] = field(default_factory=dict)
    provider: str = ""

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


def emit_metrics(metrics: Metrics) -> None:
    """Emit the canonical ``METRICS {...}`` log line for downstream parsers."""
    logger.info(f"METRICS {metrics.to_json()}")


__all__ = ["Metrics", "step_timer", "emit_metrics"]