from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from src.config import Config
from src.evaluator.deepseek_evaluator import DeepSeekEvaluator
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def make_config(**overrides) -> Config:
    defaults = {
        "deepseek_api_key": "sk-test",
        "feishu_webhook_url": "https://test.example.com",
        "ai": {"deepseek_model": "deepseek-chat", "max_candidates": 60, "top_n": 5},
    }
    defaults.update(overrides)
    return Config(**defaults)


evaluator = DeepSeekEvaluator()


def test_empty_input_returns_empty():
    assert evaluator.evaluate([], make_config()) == []


def test_parses_json_response():
    items = [NewsItem("Test News", "http://a.com/1", "Summary", "SourceA", now())]
    mock_choice = SimpleNamespace()
    mock_choice.message = SimpleNamespace()
    mock_choice.message.content = (
        '{"items": [{"candidate_id": 1, "title": "测试新闻", '
        '"chinese_summary": "这是一条测试新闻。", '
        '"importance": 8, "keywords": ["AI", "测试"]}]}'
    )
    mock_resp = SimpleNamespace(choices=[mock_choice])

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.return_value = mock_resp
        result = evaluator.evaluate(items, make_config())
        assert len(result) == 1
        assert result[0].importance == 8


def test_uses_deepseek_base_url():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    mock_choice = SimpleNamespace()
    mock_choice.message = SimpleNamespace()
    mock_choice.message.content = '{"items": []}'
    mock_resp = SimpleNamespace(choices=[mock_choice])

    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.return_value = mock_resp
        evaluator.evaluate(items, make_config())
        call_kwargs = mc.call_args[1]
        assert call_kwargs["base_url"] == "https://api.deepseek.com/v1"
        assert call_kwargs["api_key"] == "sk-test"
        assert call_kwargs["timeout"] == 60.0
        assert call_kwargs["max_retries"] == 0


def test_handles_api_error():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as mc:
        mc.return_value.chat.completions.create.side_effect = Exception("API Down")
        result = evaluator.evaluate(items, make_config(ai={**make_config().ai, "max_retries": 1}))
        assert result == []


def test_non_retryable_error_is_not_retried():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as mc, patch(
        "src.evaluator.base.time.sleep"
    ):
        mc.return_value.chat.completions.create.side_effect = Exception("bad request")
        result = evaluator.evaluate(items, make_config())

    assert result == []
    assert mc.return_value.chat.completions.create.call_count == 1


def test_connection_error_is_retried():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"items": []}'))]
    )
    with patch("src.evaluator.deepseek_evaluator.OpenAI", create=True) as mc, patch(
        "src.evaluator.base.time.sleep"
    ):
        mc.return_value.chat.completions.create.side_effect = [
            httpx.ConnectError("offline", request=request),
            response,
        ]
        result = evaluator.evaluate(
            items, make_config(ai={**make_config().ai, "max_retries": 2})
        )

    assert result == []
    assert mc.return_value.chat.completions.create.call_count == 2
