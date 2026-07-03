from datetime import datetime, timezone
from unittest.mock import patch
from src.evaluator import evaluate_news, _create_evaluator
from src.evaluator.deepseek_evaluator import DeepSeekEvaluator
from src.evaluator.rule_evaluator import RuleEvaluator
from src.config import Config
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def make_config(**overrides) -> Config:
    defaults = {
        "deepseek_api_key": "sk-test",
        "feishu_webhook_url": "https://test.example.com",
        "ai": {"provider": "deepseek", "top_n": 5},
    }
    defaults.update(overrides)
    return Config(**defaults)


# --- Factory tests ---

def test_default_provider_is_deepseek():
    evaluator = _create_evaluator(make_config(ai={}))
    assert isinstance(evaluator, DeepSeekEvaluator)


def test_explicit_deepseek():
    evaluator = _create_evaluator(make_config(ai={"provider": "deepseek"}))
    assert isinstance(evaluator, DeepSeekEvaluator)


def test_unknown_provider_defaults_to_deepseek():
    evaluator = _create_evaluator(make_config(ai={"provider": "unknown_xyz"}))
    assert isinstance(evaluator, DeepSeekEvaluator)


def test_rule_provider():
    evaluator = _create_evaluator(make_config(ai={"provider": "rule"}))
    assert isinstance(evaluator, RuleEvaluator)


# --- Facade tests ---

def test_empty_input_returns_empty():
    assert evaluate_news([], make_config()) == []


def test_falls_back_to_rule_on_failure():
    items = [NewsItem(
        "GPT-5 发布，性能提升100倍", "http://a.com/1",
        "OpenAI 发布了 GPT-5...", "机器之心", now(),
    )]
    with patch.object(DeepSeekEvaluator, "evaluate", side_effect=Exception("API Down")):
        result = evaluate_news(items, make_config())
        assert len(result) >= 1
        assert 1 <= result[0].importance <= 10


def test_rule_provider_does_not_double_fallback():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    result = evaluate_news(items, make_config(ai={"provider": "rule", "top_n": 5}))
    assert len(result) >= 1
