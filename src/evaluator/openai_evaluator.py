"""OpenAI evaluator — uses the official openai SDK with json_object mode."""
from __future__ import annotations

from loguru import logger
from openai import OpenAI

from src.evaluator._prompting import SYSTEM_PROMPT, build_user_prompt
from src.evaluator.base import BaseEvaluator
from src.evaluator.json_parser import extract_json_from_text
from src.models import EvaluatedItem, NewsItem


class OpenAiEvaluator(BaseEvaluator):
    """Evaluate news using OpenAI's chat completions API."""

    def evaluate(self, items: list[NewsItem], config) -> list[EvaluatedItem]:
        if not items:
            return []
        ai_cfg = config.ai
        top_n = ai_cfg.get("top_n", 10)
        max_candidates = ai_cfg.get("max_candidates", 60)
        max_retries = ai_cfg.get("max_retries", 3)
        request_timeout = float(ai_cfg.get("request_timeout", 60.0))
        model = ai_cfg.get("openai_model", "gpt-4o-mini")
        candidates = items[:max_candidates]

        if len(items) > max_candidates:
            logger.info(f"Truncated {len(items)} candidates to {max_candidates}")

        client = OpenAI(
            api_key=config.openai_api_key,
            timeout=request_timeout,
            max_retries=0,
        )
        prompt = build_user_prompt(candidates, top_n)

        def _call() -> str:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=4096,
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("OpenAI returned an empty response")
            return content

        raw = self._retry_call(_call, max_retries=max_retries, label="OpenAI")
        if raw is None:
            return []
        data = extract_json_from_text(raw)
        results = self._build_evaluated_items(
            data.get("items", []), candidates, top_n
        )
        logger.info(f"OpenAI evaluated: {len(results)} items (Top {top_n})")
        return results
