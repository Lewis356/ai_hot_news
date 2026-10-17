"""DeepSeek evaluator — OpenAI-compatible chat completions at api.deepseek.com."""
from __future__ import annotations

from loguru import logger
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from src.evaluator._prompting import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from src.evaluator.base import BaseEvaluator
from src.models import EvaluatedItem, NewsItem


class DeepSeekEvaluator(BaseEvaluator):
    """Evaluate news using DeepSeek's OpenAI-compatible API."""

    BASE_URL = "https://api.deepseek.com/v1"

    def evaluate(self, items: list[NewsItem], config) -> list[EvaluatedItem]:
        if not items:
            return []
        ai_cfg = config.ai
        top_n = ai_cfg.get("top_n", 10)
        max_candidates = ai_cfg.get("max_candidates", 60)
        max_retries = ai_cfg.get("max_retries", 3)
        request_timeout = float(ai_cfg.get("request_timeout", 60.0))
        model = ai_cfg.get("deepseek_model", "deepseek-chat")
        candidates = items[:max_candidates]

        if len(items) > max_candidates:
            logger.info(f"Truncated {len(items)} candidates to {max_candidates}")

        client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=self.BASE_URL,
            timeout=request_timeout,
            max_retries=0,
        )
        prompt = build_user_prompt(candidates, top_n)

        def _call(correction_prompt: str | None = None) -> str:
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            if correction_prompt:
                messages.append({"role": "user", "content": correction_prompt})
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4096,
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("DeepSeek returned an empty response")
            return content

        results = self._evaluate_with_correction(
            _call, candidates, top_n, max_retries, "DeepSeek"
        )
        logger.info(f"DeepSeek evaluated: {len(results)} items (Top {top_n})")
        return results
