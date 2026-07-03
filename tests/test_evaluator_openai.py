from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from src.evaluator.openai_evaluator import OpenAiEvaluator
from src.config import Config
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def make_config(**overrides) -> Config:
    defaults = {
        "openai_api_key": "sk-test",
        "feishu_webhook_url": "https://test.example.com",
        "ai": {"openai_model": "gpt-4o-mini", "max_candidates": 60, "top_n": 5},
    }
    defaults.update(overrides)
    return Config(**defaults)


evaluator = OpenAiEvaluator()


def test_empty_input_returns_empty():
    assert evaluator.evaluate([], make_config()) == []


def test_parses_json_response():
    items = [NewsItem("Test News", "http://a.com/1", "Summary", "SourceA", now())]
    mock_choice = SimpleNamespace()
    mock_choice.message = SimpleNamespace()
    mock_choice.message.content = (
        '{"items": [{"title": "测试新闻", "url": "http://a.com/1", '
        '"source": "SourceA", "chinese_summary": "这是一条测试新闻。", '
        '"importance": 8, "keywords": ["AI", "测试"], "published_at": "2026-06-23"}]}'
    )
    mock_resp = SimpleNamespace(choices=[mock_choice])

    with patch("src.evaluator.openai_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.return_value = mock_resp
        result = evaluator.evaluate(items, make_config())
        assert len(result) == 1
        assert result[0].importance == 8
        assert result[0].chinese_summary == "这是一条测试新闻。"


def test_handles_api_error():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    with patch("src.evaluator.openai_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.side_effect = Exception("API Down")
        result = evaluator.evaluate(items, make_config(ai={**make_config().ai, "max_retries": 1}))
        assert result == []


def test_uses_response_format_json_object():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    mock_choice = SimpleNamespace()
    mock_choice.message = SimpleNamespace()
    mock_choice.message.content = '{"items": []}'
    mock_resp = SimpleNamespace(choices=[mock_choice])

    with patch("src.evaluator.openai_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.return_value = mock_resp
        evaluator.evaluate(items, make_config())
        call_kwargs = mc.return_value.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}
