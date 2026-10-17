"""Shared validation and retry policy for news evaluator providers."""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Annotated, Callable, TypeVar

import httpx
from loguru import logger
from openai import APIConnectionError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from src.evaluator._prompting import build_correction_prompt
from src.evaluator.json_parser import extract_json_from_text
from src.models import EvaluatedItem, NewsItem
from src.utils.redact import redact

_T = TypeVar("_T")
_ValidatedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
_Keyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
]


class _ModelItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: int
    title: Annotated[_ValidatedText, StringConstraints(max_length=500)]
    chinese_summary: Annotated[_ValidatedText, StringConstraints(max_length=300)]
    importance: int = Field(ge=1, le=10)
    keywords: list[_Keyword] = Field(min_length=1, max_length=4)


class _ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[_ModelItem]


class BaseEvaluator(ABC):
    """Provider-agnostic interface for news evaluation and ranking."""

    last_error: str | None = None

    @abstractmethod
    def evaluate(
        self, items: list[NewsItem], config
    ) -> list[EvaluatedItem]:
        """Evaluate and rank news items."""
        ...

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, APIConnectionError)):
            return True
        status_code = getattr(error, "status_code", None)
        return status_code == 429 or (
            isinstance(status_code, int) and status_code >= 500
        )

    def _retry_call(
        self,
        fn: Callable[[], _T],
        *,
        max_retries: int = 3,
        label: str = "LLM",
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
    ) -> _T | None:
        """Retry only transient transport, rate-limit, and server failures."""
        for attempt in range(max_retries):
            try:
                result = fn()
                self.last_error = None
                return result
            except Exception as error:  # providers raise heterogeneous types
                safe_error = redact(str(error))
                self.last_error = redact(
                    f"{type(error).__name__}: {safe_error}"
                )[:200]
                if not self._is_retryable(error):
                    logger.error(f"{label} failed without retry: {safe_error}")
                    return None
                if attempt == max_retries - 1:
                    logger.error(f"{label} failed after {max_retries} attempts")
                    return None
                wait = min(backoff_cap, backoff_base * (2 ** attempt))
                wait += random.uniform(0, 0.5)
                logger.warning(
                    f"{label} attempt {attempt + 1}/{max_retries} failed: "
                    f"{safe_error}. Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
        return None

    def _build_evaluated_items(
        self,
        response_data: object,
        candidates: list[NewsItem],
        top_n: int,
    ) -> list[EvaluatedItem]:
        """Strictly validate model judgements and restore trusted provenance."""
        try:
            validated = _ModelResponse.model_validate(response_data)
        except ValidationError as error:
            raise ValueError(
                f"unexpected fields or invalid model output: {error}"
            ) from error

        candidates_by_id = {
            candidate_id: item
            for candidate_id, item in enumerate(candidates, 1)
        }
        results: list[EvaluatedItem] = []
        seen_candidate_ids: set[int] = set()
        for item in validated.items:
            candidate = candidates_by_id.get(item.candidate_id)
            if candidate is None:
                raise ValueError(f"unknown candidate_id: {item.candidate_id}")
            if item.candidate_id in seen_candidate_ids:
                raise ValueError(f"duplicate candidate_id: {item.candidate_id}")
            seen_candidate_ids.add(item.candidate_id)
            results.append(EvaluatedItem(
                title=item.title,
                url=candidate.url,
                source=candidate.source,
                chinese_summary=item.chinese_summary,
                importance=item.importance,
                keywords=item.keywords,
                published_at=candidate.published_at,
            ))
        results.sort(key=lambda item: item.importance, reverse=True)
        return results[:top_n]

    def _validated_items_with_correction(
        self,
        raw: str,
        candidates: list[NewsItem],
        top_n: int,
        correction_call: Callable[[str], str | None],
    ) -> list[EvaluatedItem]:
        """Validate output, allowing exactly one model correction request."""
        try:
            data = extract_json_from_text(raw)
            return self._build_evaluated_items(data, candidates, top_n)
        except (TypeError, ValueError) as error:
            safe_error = redact(str(error))[:300]
            logger.warning(f"Model output validation failed; requesting one correction: {safe_error}")
            corrected = correction_call(safe_error)
            if corrected is None:
                raise
            data = extract_json_from_text(corrected)
            return self._build_evaluated_items(data, candidates, top_n)

    def _evaluate_with_correction(
        self,
        call: Callable[[str | None], str],
        candidates: list[NewsItem],
        top_n: int,
        max_retries: int,
        label: str,
    ) -> list[EvaluatedItem]:
        """Call one provider, then allow one schema-correction request."""
        self.last_error = None
        raw = self._retry_call(lambda: call(None), max_retries=max_retries, label=label)
        if raw is None:
            return []
        return self._validated_items_with_correction(
            raw,
            candidates,
            top_n,
            lambda error: self._retry_call(
                lambda: call(build_correction_prompt(raw, error)),
                max_retries=1,
                label=f"{label} output correction",
            ),
        )
