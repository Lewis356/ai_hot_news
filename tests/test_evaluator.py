from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.config import Config
from src.evaluator import _create_evaluator, evaluate_news
from src.evaluator.deepseek_evaluator import DeepSeekEvaluator
from src.evaluator.rule_evaluator import RuleEvaluator
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
    result = evaluate_news([], make_config())

    assert result.items == []
    assert result.requested_provider == "deepseek"
    assert result.used_provider == "deepseek"
    assert result.fallback_used is False
    assert result.fallback_reason is None


def test_reports_the_provider_that_evaluated_the_items():
    item = NewsItem("Test", "http://a.com/1", "", "S", now())
    evaluated = RuleEvaluator().evaluate([item], make_config())

    with patch.object(DeepSeekEvaluator, "evaluate", return_value=evaluated):
        result = evaluate_news([item], make_config())

    assert result.items == evaluated
    assert result.requested_provider == "deepseek"
    assert result.used_provider == "deepseek"
    assert result.fallback_used is False
    assert result.fallback_reason is None


def test_falls_back_to_rule_on_failure():
    items = [NewsItem(
        "GPT-5 发布，性能提升100倍", "http://a.com/1",
        "OpenAI 发布了 GPT-5...", "机器之心", now(),
    )]
    with patch.object(DeepSeekEvaluator, "evaluate", side_effect=Exception("API Down")):
        result = evaluate_news(items, make_config())

    assert len(result.items) >= 1
    assert 1 <= result.items[0].importance <= 10
    assert result.requested_provider == "deepseek"
    assert result.used_provider == "rule"
    assert result.fallback_used is True
    assert result.fallback_reason is not None
    assert "API Down" in result.fallback_reason


def test_falls_back_to_rule_on_empty_primary_output():
    item = NewsItem("Test", "http://a.com/1", "", "S", now())

    with patch.object(DeepSeekEvaluator, "evaluate", return_value=[]):
        result = evaluate_news([item], make_config())

    assert len(result.items) == 1
    assert result.used_provider == "rule"
    assert result.fallback_used is True
    assert result.fallback_reason == "primary provider returned no items"


def test_fallback_keeps_provider_error_summary():
    item = NewsItem("Test", "http://a.com/1", "", "S", now())

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.side_effect = Exception(
            "Insufficient Balance"
        )
        result = evaluate_news([item], make_config())

    assert result.used_provider == "rule"
    assert result.fallback_reason is not None
    assert "Insufficient Balance" in result.fallback_reason


def test_rule_provider_does_not_double_fallback():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    result = evaluate_news(items, make_config(ai={"provider": "rule", "top_n": 5}))

    assert len(result.items) >= 1
    assert result.requested_provider == "rule"
    assert result.used_provider == "rule"
    assert result.fallback_used is False
    assert result.fallback_reason is None


def test_rule_provider_failure_is_not_retried_as_a_fallback():
    item = NewsItem("Test", "http://a.com/1", "", "S", now())
    config = make_config(ai={"provider": "rule", "top_n": 5})

    with patch.object(RuleEvaluator, "evaluate", side_effect=RuntimeError("rule failed")):
        with pytest.raises(RuntimeError, match="rule failed"):
            evaluate_news([item], config)


def test_llm_output_enriches_a_candidate_without_replacing_its_provenance():
    published_at = datetime(2026, 10, 16, 8, 30, tzinfo=timezone.utc)
    item = NewsItem(
        "Original title",
        "https://trusted.example/news/1",
        "Original summary",
        "Trusted Source",
        published_at,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "中文标题", '
            '"chinese_summary": "中文摘要", "importance": 8, '
            '"keywords": ["AI", "发布"]}]}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.return_value = response
        result = evaluate_news([item], make_config())

    assert result.used_provider == "deepseek"
    assert result.items[0].title == "中文标题"
    assert result.items[0].url == item.url
    assert result.items[0].source == item.source
    assert result.items[0].published_at == published_at


def test_llm_prompt_uses_candidate_ids_and_keeps_provenance_out_of_the_output_schema():
    item = NewsItem(
        "Original title",
        "https://trusted.example/news/1",
        "Original summary",
        "Trusted Source",
        now(),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "中文标题", '
            '"chinese_summary": "中文摘要", "importance": 8, '
            '"keywords": ["AI"]}]}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.return_value = response
        evaluate_news([item], make_config())

    messages = client.return_value.chat.completions.create.call_args.kwargs["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert '"candidate_id": 1' in user_prompt
    assert item.url not in user_prompt
    assert '"url"' not in system_prompt
    assert '"source"' not in system_prompt
    assert '"published_at"' not in system_prompt


def test_duplicate_candidate_ids_in_model_output_trigger_rule_fallback():
    items = [
        NewsItem("First", "https://trusted.example/1", "", "Source", now()),
        NewsItem("Second", "https://trusted.example/2", "", "Source", now()),
    ]
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": ['
            '{"candidate_id": 1, "title": "标题一", "chinese_summary": "摘要一", '
            '"importance": 8, "keywords": ["AI"]},'
            '{"candidate_id": 1, "title": "标题二", "chinese_summary": "摘要二", '
            '"importance": 7, "keywords": ["模型"]}'
            ']}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.return_value = response
        result = evaluate_news(items, make_config())

    assert result.used_provider == "rule"
    assert result.fallback_used is True
    assert result.fallback_reason is not None
    assert "duplicate candidate_id" in result.fallback_reason


def test_model_output_with_provenance_fields_triggers_rule_fallback():
    item = NewsItem(
        "Original",
        "https://trusted.example/1",
        "",
        "Trusted Source",
        now(),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "中文标题", '
            '"chinese_summary": "中文摘要", "importance": 8, "keywords": ["AI"], '
            '"url": "https://attacker.example", "source": "Fake", '
            '"published_at": "2099-01-01"}]}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.return_value = response
        result = evaluate_news([item], make_config())

    assert result.used_provider == "rule"
    assert result.fallback_used is True
    assert result.fallback_reason is not None
    assert "unexpected fields" in result.fallback_reason
    assert result.items[0].url == item.url
    assert result.items[0].source == item.source


@pytest.mark.parametrize(
    "invalid_fields",
    [
        '"chinese_summary": "", "importance": 8, "keywords": ["AI"]',
        '"chinese_summary": "摘要", "importance": 11, "keywords": ["AI"]',
        '"chinese_summary": "摘要", "importance": 8, '
        '"keywords": ["1", "2", "3", "4", "5"]',
    ],
)
def test_invalid_model_content_triggers_rule_fallback(invalid_fields):
    item = NewsItem("Original", "https://trusted.example/1", "", "Source", now())
    content = (
        '{"items": [{"candidate_id": 1, "title": "标题", '
        f"{invalid_fields}" + "}]}"
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.return_value = response
        result = evaluate_news([item], make_config())

    assert result.used_provider == "rule"
    assert result.fallback_used is True


def test_invalid_model_output_gets_one_correction_attempt():
    item = NewsItem("Original", "https://trusted.example/1", "", "Source", now())
    invalid = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "标题", '
            '"chinese_summary": "", "importance": 8, "keywords": ["AI"]}]}'
        )))]
    )
    corrected = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "标题", '
            '"chinese_summary": "有效摘要", "importance": 8, "keywords": ["AI"]}]}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.side_effect = [invalid, corrected]
        result = evaluate_news([item], make_config())

    assert result.used_provider == "deepseek"
    assert result.fallback_used is False
    assert result.items[0].chinese_summary == "有效摘要"
    assert client.return_value.chat.completions.create.call_count == 2


def test_top_level_list_output_gets_one_correction_attempt():
    item = NewsItem("Original", "https://trusted.example/1", "", "Source", now())
    invalid = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
    )
    corrected = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=(
            '{"items": [{"candidate_id": 1, "title": "标题", '
            '"chinese_summary": "有效摘要", "importance": 8, "keywords": ["AI"]}]}'
        )))]
    )

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as client:
        client.return_value.chat.completions.create.side_effect = [invalid, corrected]
        result = evaluate_news([item], make_config())

    assert result.used_provider == "deepseek"
    assert client.return_value.chat.completions.create.call_count == 2
