"""Rule-based news evaluator using heuristics. No API key required."""
import re

from src.models import NewsItem, EvaluatedItem
from src.evaluator.base import BaseEvaluator


HIGH_WEIGHT_KEYWORDS = {
    "大模型": 3, "GPT": 3, "GPT-4": 3, "GPT-5": 4, "开源": 3,
    "发布": 2, "融资": 3, "收购": 3, "算力": 2, "GPU": 2,
    "芯片": 2, "AGI": 3, "突破": 2, "Sora": 3, "Llama": 2,
    "Claude": 2, "Gemini": 2, "训练": 2, "推理": 2,
    "多模态": 2, "RAG": 2, "微调": 2, "Agent": 2,
}

MEDIUM_WEIGHT_KEYWORDS = {
    "更新": 1, "合作": 1, "投资": 1, "研究": 1, "论文": 1,
    "API": 1, "模型": 1, "数据": 1, "安全": 1, "监管": 1,
    "应用": 1, "企业": 1, "开发者": 1, "基准": 1, "评测": 1,
    "机器人": 1, "自动驾驶": 2, "编程": 1, "代码": 1,
}

SOURCE_WEIGHTS = {
    "机器之心": 3, "量子位": 3, "TechCrunch": 2, "TechCrunch AI": 2,
}
DEFAULT_SOURCE_WEIGHT = 1


class RuleEvaluator(BaseEvaluator):
    """Evaluates news using keyword matching, source priority, and title
    heuristics. No API key required — works entirely offline."""

    def evaluate(self, items, config) -> list[EvaluatedItem]:
        if not items:
            return []

        ai_config = config.ai
        top_n = ai_config.get("top_n", 10)
        max_candidates = ai_config.get("max_candidates", 60)
        candidates = items[:max_candidates]
        results = []

        for item in candidates:
            kw_score = self._score_keywords(item)
            src_weight = self._score_source(item.source)
            title_score = self._score_title(item.title)

            raw = kw_score * 0.5 + src_weight * 0.3 + title_score * 0.2
            importance = max(1, min(10, round(raw)))

            results.append(EvaluatedItem(
                title=item.title,
                url=item.url,
                source=item.source,
                chinese_summary=self._generate_summary(item),
                importance=importance,
                keywords=self._extract_keywords(item.title),
                published_at=item.published_at,
            ))

        results.sort(key=lambda x: x.importance, reverse=True)
        return results[:top_n]

    def _score_keywords(self, item) -> float:
        text = (item.title + " " + item.summary).lower()
        score = 0.0
        for kw, w in HIGH_WEIGHT_KEYWORDS.items():
            if kw.lower() in text:
                score += w
        for kw, w in MEDIUM_WEIGHT_KEYWORDS.items():
            if kw.lower() in text:
                score += w
        return min(10.0, max(1.0, score * 0.7))

    def _score_source(self, source: str) -> float:
        return float(SOURCE_WEIGHTS.get(source, DEFAULT_SOURCE_WEIGHT))

    def _score_title(self, title: str) -> float:
        score = 5.0
        if len(title) < 10:
            score -= 1
        elif 20 <= len(title) <= 80:
            score += 1
        if re.search(r'\d', title):
            score += 1
        if "?" in title or "？" in title:
            score -= 0.5
        return max(1.0, min(10.0, score))

    def _generate_summary(self, item) -> str:
        if item.summary and item.summary.strip():
            text = item.summary.strip()
            if len(text) > 100:
                return text[:100] + "..."
            return text
        return f"相关报道：{item.title}"

    def _extract_keywords(self, title: str) -> list[str]:
        text = title.lower()
        found = []
        all_kw = {**HIGH_WEIGHT_KEYWORDS, **MEDIUM_WEIGHT_KEYWORDS}
        for kw, w in all_kw.items():
            if kw.lower() in text:
                found.append((kw, w))
        found.sort(key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in found[:4]]
