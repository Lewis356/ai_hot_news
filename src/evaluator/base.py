"""Abstract base class for news evaluator providers.

Subclasses inherit two helpers used across every LLM-backed evaluator:

* ``_retry_call(fn, ...)`` — exponential-backoff retry loop that scrubs
  exception messages before logging.
* ``_sanitize_item(it)`` — coerce / clamp LLM JSON output into the shape
  ``EvaluatedItem`` expects, with defensive bounds-checking so a chatty
  model can't break downstream rendering.
"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

from loguru import logger

from src.models import EvaluatedItem, NewsItem
from src.utils.redact import redact

# Bounds used when validating LLM-returned fields. A model that emits
# importance=999 or a 50-keyword blob would otherwise propagate straight
# into the Feishu card.
IMPORTANCE_MIN = 1
IMPORTANCE_MAX = 10
IMPORTANCE_DEFAULT = 5
MAX_TITLE_LEN = 500
MAX_SUMMARY_LEN = 300
MAX_SOURCE_LEN = 50
MAX_KEYWORDS = 4

_T = TypeVar("_T")


class BaseEvaluator(ABC):
    """Provider-agnostic interface for news evaluation and ranking."""

    @abstractmethod
    def evaluate(
        self, items: list[NewsItem], config
    ) -> list[EvaluatedItem]:
        """Evaluate and rank news items.

        Args:
            items: Candidate news items to evaluate.
            config: Config dataclass with provider-specific settings.

        Returns:
            Top N evaluated items, sorted by importance descending.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def _retry_call(
        self,
        fn: Callable[[], _T],
        *,
        max_retries: int = 3,
        label: str = "LLM",
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
    ) -> _T | None:
        """Call ``fn()`` with exponential backoff + jitter.

        Returns the function's return value on success, or ``None`` once all
        retries are exhausted. Exception messages are scrubbed before logging
        so API keys never leak to disk.
        """
        for attempt in range(max_retries):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001 — providers raise heterogeneous types
                wait = min(backoff_cap, backoff_base * (2 ** attempt))
                wait += random.uniform(0, 0.5)
                logger.warning(
                    redact(
                        f"{label} attempt {attempt + 1}/{max_retries} failed: "
                        f"{e}. Retrying in {wait:.1f}s..."
                    )
                )
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    logger.error(
                        f"{label} failed after {max_retries} attempts"
                    )
        return None

    @staticmethod
    def _sanitize_item(it: dict) -> dict:
        """Coerce / clamp one LLM-emitted item dict into ``EvaluatedItem`` shape.

        Defensive defaults:
          * ``importance`` is clamped to ``[IMPORTANCE_MIN, IMPORTANCE_MAX]``.
          * ``keywords`` is deduplicated and truncated to ``MAX_KEYWORDS``.
          * Long strings are truncated to card-safe lengths.
          * URLs that aren't http(s) are dropped (markdown link target).
        """
        raw_imp = it.get("importance", IMPORTANCE_DEFAULT)
        try:
            importance = int(raw_imp)
        except (TypeError, ValueError):
            importance = IMPORTANCE_DEFAULT
        importance = max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, importance))

        raw_kw = it.get("keywords") or []
        if not isinstance(raw_kw, list):
            raw_kw = [str(raw_kw)]
        seen: set[str] = set()
        keywords: list[str] = []
        for kw in raw_kw:
            kw_s = str(kw).strip()
            if not kw_s or kw_s in seen:
                continue
            seen.add(kw_s)
            keywords.append(kw_s[:30])
            if len(keywords) >= MAX_KEYWORDS:
                break

        url = (it.get("url") or "").strip()
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                url = ""
        except (ValueError, AttributeError):
            url = ""

        title = str(it.get("title") or "").strip()[:MAX_TITLE_LEN]
        source = str(it.get("source") or "").strip()[:MAX_SOURCE_LEN]
        chinese_summary = str(it.get("chinese_summary") or "").strip()[:MAX_SUMMARY_LEN]
        published_at = it.get("published_at") or ""

        return {
            "title": title,
            "url": url,
            "source": source,
            "chinese_summary": chinese_summary,
            "importance": importance,
            "keywords": keywords,
            "published_at": published_at,
        }

    def _build_evaluated_items(
        self, items_raw: list[dict], top_n: int
    ) -> list[EvaluatedItem]:
        """Sanitize, build, sort and truncate raw LLM items into top-N."""
        results: list[EvaluatedItem] = []
        for it in items_raw or []:
            if not isinstance(it, dict):
                continue
            sanitized = self._sanitize_item(it)
            results.append(EvaluatedItem(**sanitized))
        results.sort(key=lambda x: x.importance, reverse=True)
        return results[:top_n]