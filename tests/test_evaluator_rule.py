from datetime import datetime, timezone
from src.evaluator.rule_evaluator import RuleEvaluator
from src.config import Config
from src.models import NewsItem


def now():
    return datetime.now(timezone.utc)


def make_config(**overrides) -> Config:
    defaults = {
        "feishu_webhook_url": "https://test.example.com",
        "ai": {"top_n": 5},
    }
    defaults.update(overrides)
    return Config(**defaults)


evaluator = RuleEvaluator()


def test_empty_input_returns_empty():
    assert evaluator.evaluate([], make_config()) == []


def test_single_item_gets_scored():
    items = [
        NewsItem(
            "GPT-5 正式发布，性能提升100倍",
            "http://a.com/1",
            "OpenAI 今天正式发布了 GPT-5 大模型...",
            "机器之心", now(),
        )
    ]
    result = evaluator.evaluate(items, make_config())
    assert len(result) == 1
    assert 1 <= result[0].importance <= 10
    assert len(result[0].chinese_summary) > 0
    assert len(result[0].keywords) > 0
    assert result[0].source == "机器之心"


def test_high_weight_keywords_score_higher():
    high = NewsItem("大模型开源 GPT-5 融资 重大突破", "http://a.com/1", "", "S", now())
    low = NewsItem("普通更新 小改进", "http://a.com/2", "", "S", now())
    result = evaluator.evaluate([low, high], make_config())
    assert result[0].importance >= result[1].importance


def test_source_priority_affects_score():
    a = NewsItem("相同标题测试新闻", "http://a.com/1", "", "机器之心", now())
    b = NewsItem("相同标题测试新闻", "http://a.com/2", "", "未知来源", now())
    result = evaluator.evaluate([b, a], make_config())
    mz = [r for r in result if r.source == "机器之心"][0]
    unk = [r for r in result if r.source == "未知来源"][0]
    assert mz.importance >= unk.importance


def test_summary_uses_original_when_present():
    items = [
        NewsItem("标题", "http://a.com/1", "这是一段原始摘要内容，描述了新闻的详细信息。", "S", now())
    ]
    result = evaluator.evaluate(items, make_config())
    assert "这是一段原始摘要内容" in result[0].chinese_summary


def test_summary_falls_back_to_title():
    items = [NewsItem("AI行业最新动态：多家公司发布新品", "http://a.com/1", "", "S", now())]
    result = evaluator.evaluate(items, make_config())
    assert len(result[0].chinese_summary) > 0


def test_keywords_extracted_from_title():
    items = [NewsItem("GPT-5 大模型开源发布，推动AGI发展", "http://a.com/1", "", "S", now())]
    result = evaluator.evaluate(items, make_config())
    assert 1 <= len(result[0].keywords) <= 4


def test_sorted_by_importance_desc():
    items = [NewsItem(f"News {i}", f"http://a.com/{i}", "", "S", now()) for i in range(10)]
    result = evaluator.evaluate(items, make_config(ai={"top_n": 10}))
    importances = [r.importance for r in result]
    assert importances == sorted(importances, reverse=True)


def test_respects_top_n():
    items = [NewsItem(f"News {i}", f"http://a.com/{i}", "", "S", now()) for i in range(20)]
    result = evaluator.evaluate(items, make_config(ai={"top_n": 3}))
    assert len(result) <= 3


def test_published_at_preserved():
    pub = now()
    items = [NewsItem("Test", "http://a.com/1", "", "S", pub)]
    result = evaluator.evaluate(items, make_config())
    assert result[0].published_at == pub
