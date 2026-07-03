"""DeepSeek evaluator — OpenAI-compatible chat completions at api.deepseek.com."""
from __future__ import annotations

from loguru import logger

from src.models import EvaluatedItem, NewsItem
from src.evaluator.base import BaseEvaluator
from src.evaluator._prompting import SYSTEM_PROMPT, build_user_prompt
from src.evaluator.json_parser import extract_json_from_text

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover — requirements.txt pins openai
    OpenAI = None


class DeepSeekEvaluator(BaseEvaluator):
    """Evaluate news using DeepSeek's OpenAI-compatible API."""

    BASE_URL = "https://api.deepseek.com/v1"

    def evaluate(self, items: list[NewsItem], config) -> list[EvaluatedItem]:
        if not items:
            return []
        if OpenAI is None:
            raise ImportError(
                "openai package is required for DeepSeek provider. "
                "Install: pip install openai"
            )

        ai_cfg = config.ai
        top_n = ai_cfg.get("top_n", 10)
        max_candidates = ai_cfg.get("max_candidates", 60)
        max_retries = ai_cfg.get("max_retries", 3)
        model = ai_cfg.get("deepseek_model", "deepseek-chat")
        candidates = items[:max_candidates]

        if len(items) > max_candidates:
            logger.info(f"Truncated {len(items)} candidates to {max_candidates}")

        client = OpenAI(api_key=config.deepseek_api_key, base_url=self.BASE_URL)
        prompt = build_user_prompt(candidates, top_n)

        def _call() -> str:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                temperature=0.1,
            )
            return response.choices[0].message.content

        raw = self._retry_call(_call, max_retries=max_retries, label="DeepSeek")
        if raw is None:
            return []
        data = extract_json_from_text(raw)
        results = self._build_evaluated_items(data.get("items", []), top_n)
        logger.info(f"DeepSeek evaluated: {len(results)} items (Top {top_n})")
        return results