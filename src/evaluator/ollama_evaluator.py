"""Ollama evaluator — local model via OpenAI-compatible /v1/chat/completions."""
from __future__ import annotations

import httpx
from loguru import logger

from src.evaluator._prompting import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from src.evaluator.base import BaseEvaluator
from src.models import EvaluatedItem, NewsItem


class OllamaEvaluator(BaseEvaluator):
    """Evaluate news using a local Ollama model via its OpenAI-compatible API."""

    def evaluate(self, items: list[NewsItem], config) -> list[EvaluatedItem]:
        if not items:
            return []

        ai_cfg = config.ai
        top_n = ai_cfg.get("top_n", 10)
        max_candidates = ai_cfg.get("max_candidates", 60)
        max_retries = ai_cfg.get("max_retries", 3)
        timeout = float(
            ai_cfg.get("ollama_timeout", ai_cfg.get("request_timeout", 60.0))
        )
        model = ai_cfg.get("ollama_model", "qwen2.5:7b")
        base_url = (config.ollama_base_url or "http://localhost:11434").rstrip("/")
        candidates = items[:max_candidates]

        if len(items) > max_candidates:
            logger.info(f"Truncated {len(items)} candidates to {max_candidates}")

        api_url = f"{base_url}/v1/chat/completions"
        prompt = build_user_prompt(candidates, top_n)

        def _call(correction_prompt: str | None = None) -> str:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            if correction_prompt:
                messages.append({"role": "user", "content": correction_prompt})
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(api_url, json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096},
                })
                resp.raise_for_status()
                payload = resp.json()
            return payload["choices"][0]["message"]["content"]

        results = self._evaluate_with_correction(
            _call, candidates, top_n, max_retries, "Ollama"
        )
        logger.info(f"Ollama evaluated: {len(results)} items (Top {top_n})")
        return results
