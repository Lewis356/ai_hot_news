from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.evaluator.ollama_evaluator import OllamaEvaluator
from src.config import Config
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def make_config(**overrides) -> Config:
    defaults = {
        "ollama_base_url": "http://localhost:11434",
        "feishu_webhook_url": "https://test.example.com",
        "ai": {"ollama_model": "qwen2.5:7b", "max_candidates": 60, "top_n": 5},
    }
    defaults.update(overrides)
    return Config(**defaults)


evaluator = OllamaEvaluator()


def test_empty_input_returns_empty():
    assert evaluator.evaluate([], make_config()) == []


def test_parses_clean_json_response():
    items = [NewsItem("Test News", "http://a.com/1", "Summary", "SourceA", now())]
    mock_httpx = MagicMock()
    mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
    mock_httpx.__exit__ = MagicMock(return_value=False)
    mock_httpx.post.return_value.json.return_value = {
        "choices": [{"message": {"content": (
            '{"items": [{"title": "测试新闻", "url": "http://a.com/1", '
            '"source": "SourceA", "chinese_summary": "这是一条测试新闻。", '
            '"importance": 8, "keywords": ["AI", "测试"], "published_at": "2026-06-23"}]}'
        )}}]
    }
    mock_httpx.post.return_value.raise_for_status = MagicMock()

    with patch("src.evaluator.ollama_evaluator.httpx.Client") as mc:
        mc.return_value = mock_httpx
        result = evaluator.evaluate(items, make_config())
        assert len(result) == 1
        assert result[0].importance == 8
        assert result[0].chinese_summary == "这是一条测试新闻。"
        assert "AI" in result[0].keywords


def test_parses_markdown_wrapped_json():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    mock_httpx = MagicMock()
    mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
    mock_httpx.__exit__ = MagicMock(return_value=False)
    mock_httpx.post.return_value.json.return_value = {
        "choices": [{"message": {"content": (
            '```json\n{"items": [{"title": "测试", "url": "http://a.com/1", '
            '"source": "S", "chinese_summary": "摘要。", "importance": 5, '
            '"keywords": ["AI"], "published_at": "2026-06-23"}]}\n```'
        )}}]
    }
    mock_httpx.post.return_value.raise_for_status = MagicMock()

    with patch("src.evaluator.ollama_evaluator.httpx.Client") as mc:
        mc.return_value = mock_httpx
        result = evaluator.evaluate(items, make_config())
        assert len(result) == 1
        assert result[0].importance == 5


def test_handles_connection_error():
    items = [NewsItem("Test", "http://a.com/1", "", "S", now())]
    with patch("src.evaluator.ollama_evaluator.httpx.Client") as mc:
        mc.side_effect = Exception("Connection refused")
        result = evaluator.evaluate(items, make_config(ai={**make_config().ai, "max_retries": 1}))
        assert result == []
