"""Multi-provider news evaluator.

Exposes :func:`evaluate_news` — a facade that selects the evaluator for
``config.ai.provider`` and transparently falls back to ``RuleEvaluator`` on
failure (unless the operator already chose ``rule``).
"""
from __future__ import annotations

from typing import Type

from loguru import logger

from src.evaluator.base import BaseEvaluator
from src.evaluator.deepseek_evaluator import DeepSeekEvaluator
from src.evaluator.ollama_evaluator import OllamaEvaluator
from src.evaluator.openai_evaluator import OpenAiEvaluator
from src.evaluator.rule_evaluator import RuleEvaluator
from src.models import EvaluatedItem, NewsItem
from src.utils.redact import redact

PROVIDER_REGISTRY: dict[str, Type[BaseEvaluator]] = {
    "deepseek": DeepSeekEvaluator,
    "openai": OpenAiEvaluator,
    "ollama": OllamaEvaluator,
    "rule": RuleEvaluator,
}


def _create_evaluator(config) -> BaseEvaluator:
    provider = config.ai.get("provider", "deepseek")
    cls = PROVIDER_REGISTRY.get(provider)
    if cls is None:
        logger.warning(
            f"Unknown AI provider '{provider}', falling back to deepseek"
        )
        cls = DeepSeekEvaluator
    return cls()


def _safe_evaluate(
    evaluator: BaseEvaluator, items: list[NewsItem], config, provider: str
) -> list[EvaluatedItem]:
    """Run ``evaluator.evaluate()`` and fall back to rule-based on error.

    When the primary provider is already ``rule`` we re-raise so a broken
    heuristic isn't silently swallowed.
    """
    try:
        return evaluator.evaluate(items, config)
    except Exception as e:  # noqa: BLE001 — providers raise heterogeneous types
        if provider == "rule":
            raise
        logger.error(
            redact(
                f"Provider '{provider}' failed: {e}. "
                f"Falling back to rule-based evaluator."
            )
        )
        return RuleEvaluator().evaluate(items, config)


def evaluate_news(
    items: list[NewsItem], config
) -> list[EvaluatedItem]:
    """Evaluate and rank news items using the configured AI provider.

    Falls back to rule-based evaluation if the primary provider raises.
    Returns an empty list when ``items`` is empty.
    """
    if not items:
        logger.info("No candidate news items to evaluate")
        return []

    provider = config.ai.get("provider", "deepseek")
    evaluator = _create_evaluator(config)
    return _safe_evaluate(evaluator, items, config, provider)


__all__ = [
    "BaseEvaluator",
    "DeepSeekEvaluator",
    "OpenAiEvaluator",
    "OllamaEvaluator",
    "RuleEvaluator",
    "evaluate_news",
]