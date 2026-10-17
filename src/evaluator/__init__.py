"""Multi-provider news evaluator.

Exposes :func:`evaluate_news` — a facade that selects the evaluator for
``config.ai.provider`` and transparently falls back to ``RuleEvaluator`` on
failure (unless the operator already chose ``rule``).
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from src.evaluator.base import BaseEvaluator
from src.evaluator.deepseek_evaluator import DeepSeekEvaluator
from src.evaluator.ollama_evaluator import OllamaEvaluator
from src.evaluator.openai_evaluator import OpenAiEvaluator
from src.evaluator.rule_evaluator import RuleEvaluator
from src.models import EvaluatedItem, NewsItem
from src.utils.redact import redact

PROVIDER_REGISTRY: dict[str, type[BaseEvaluator]] = {
    "deepseek": DeepSeekEvaluator,
    "openai": OpenAiEvaluator,
    "ollama": OllamaEvaluator,
    "rule": RuleEvaluator,
}


@dataclass
class EvaluationResult:
    """Outcome of evaluating one batch of candidate news."""

    items: list[EvaluatedItem]
    requested_provider: str
    used_provider: str
    fallback_used: bool
    fallback_reason: str | None


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
) -> EvaluationResult:
    """Run ``evaluator.evaluate()`` and fall back to rule-based on error.

    When the primary provider is already ``rule`` we re-raise so a broken
    heuristic isn't silently swallowed.
    """
    try:
        evaluated = evaluator.evaluate(items, config)
    except Exception as e:  # noqa: BLE001 — providers raise heterogeneous types
        if provider == "rule":
            raise
        reason = redact(f"{type(e).__name__}: {e}")[:200]
        logger.error(
            redact(
                f"Provider '{provider}' failed: {e}. "
                f"Falling back to rule-based evaluator."
            )
        )
        return EvaluationResult(
            RuleEvaluator().evaluate(items, config),
            provider,
            "rule",
            True,
            reason,
        )
    if not evaluated and provider != "rule":
        reason = evaluator.last_error or "primary provider returned no items"
        logger.error(
            f"Provider '{provider}' returned no items. "
            "Falling back to rule-based evaluator."
        )
        return EvaluationResult(
            RuleEvaluator().evaluate(items, config),
            provider,
            "rule",
            True,
            reason,
        )
    return EvaluationResult(evaluated, provider, provider, False, None)


def evaluate_news(
    items: list[NewsItem], config
) -> EvaluationResult:
    """Evaluate and rank news items using the configured AI provider.

    Falls back to rule-based evaluation if the primary provider raises.
    Empty input returns an ``EvaluationResult`` whose ``items`` is empty.
    """
    if not items:
        logger.info("No candidate news items to evaluate")
        provider = config.ai.get("provider", "deepseek")
        return EvaluationResult([], provider, provider, False, None)

    provider = config.ai.get("provider", "deepseek")
    evaluator = _create_evaluator(config)
    return _safe_evaluate(evaluator, items, config, provider)


__all__ = [
    "BaseEvaluator",
    "DeepSeekEvaluator",
    "OpenAiEvaluator",
    "OllamaEvaluator",
    "RuleEvaluator",
    "EvaluationResult",
    "evaluate_news",
]
