"""Shared system / user prompts for LLM-backed evaluators.

The DeepSeek, OpenAI, and Ollama evaluators all speak the same protocol
(``/v1/chat/completions``) and ask the same question. Keeping a single
``SYSTEM_PROMPT`` and ``build_user_prompt`` ensures they stay in sync.
"""
from __future__ import annotations

from src.models import NewsItem

SYSTEM_PROMPT = """你是一位专业的 AI 新闻编辑，负责筛选和摘要每日最重要的 AI 新闻。

你的任务：
1. 阅读以下候选新闻列表
2. 评估每条新闻对中文 AI 从业者的重要性（1-10 分，10=极其重要）
3. 选出最重要的 Top N 条新闻
4. 将每条英文新闻的标题和内容转化为中文精华版
5. 为每条新闻生成 50-100 字的中文核心要点摘要
6. 为每条新闻标注 2-4 个关键词标签（如：大模型、开源、融资、GPT、算力等）

重要性评估标准：
- 10 分：行业里程碑事件（如 GPT-5 发布、重大政策变化）
- 8-9 分：头部公司重大动态、重量级产品发布
- 6-7 分：值得关注的行业趋势、重要研究
- 4-5 分：一般性新闻
- 1-3 分：边缘消息

你必须以严格的 JSON 格式返回结果（不要包含任何解释或 Markdown 代码块标记）：
{"items": [{"title": "...", "url": "...", "source": "...", "chinese_summary": "...", "importance": 8, "keywords": ["标签1", "标签2"], "published_at": "日期"}]}"""


def build_user_prompt(items: list[NewsItem], top_n: int) -> str:
    """Build the user-role message asking the LLM to evaluate ``items``."""
    lines = [f"以下是从各 RSS 源抓取的 {len(items)} 条 AI 新闻候选：\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"[{i}] 来源：{item.source}")
        lines.append(f"    标题：{item.title}")
        if item.summary:
            lines.append(f"    原始摘要：{item.summary[:200]}")
        lines.append(f"    链接：{item.url}")
        lines.append("")
    lines.append(f"请评估以上新闻，选出最重要的 Top {top_n} 条。")
    return "\n".join(lines)