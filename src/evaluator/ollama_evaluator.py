"""Ollama evaluator — local model via OpenAI-compatible /v1/chat/completions."""
from __future__ import annotations

import httpx
from loguru import logger

from src.models import EvaluatedItem, NewsItem
from src.evaluator.base import BaseEvaluator
from src.evaluator._prompting import SYSTEM_PROMPT, build_user_prompt
from src.evaluator.json_parser import extract_json_from_text


class OllamaEvaluator(BaseEvaluator):
    """Evaluate news using a local Ollama model via its OpenAI-compatible API."""

    def evaluate(self, items: list[NewsItem], config) -> list[EvaluatedItem]:
        if not items:
            return []

        ai_cfg = config.ai
        top_n = ai_cfg.get("top_n", 10)
        max_candidates = ai_cfg.get("max_candidates", 60)
        max_retries = ai_cfg.get("max_retries", 3)
        timeout = float(ai_cfg.get("ollama_timeout", 120.0))
        model = ai_cfg.get("ollama_model", "qwen2.5:7b")
        base_url = (config.ollama_base_url or "http://localhost:11434").rstrip("/")
        candidates = items[:max_candidates]

        if len(items) > max_candidates:
            logger.info(f"Truncated {len(items)} candidates to {max_candidates}")

        api_url = f"{base_url}/v1/chat/completions"
        prompt = build_user_prompt(candidates, top_n)

        def _call() -> str:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(api_url, json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096},
                })
                resp.raise_for_status()
                payload = resp.json()
            return payload["choices"][0]["message"]["content"]

        raw = self._retry_call(_call, max_retries=max_retries, label="Ollama")
        if raw is None:
            return []
        data = extract_json_from_text(raw)
        results = self._build_evaluated_items(data.get("items", []), top_n)
        logger.info(f"Ollama evaluated: {len(results)} items (Top {top_n})")
        return results