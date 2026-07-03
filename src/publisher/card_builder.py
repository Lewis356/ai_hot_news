"""Feishu interactive card builder — beautified, escaped, ranked.

Produces a Lark/Feishu interactive card JSON. Highlights:

  * Header color follows the top item's importance (red → orange → blue → green).
  * Rank 1-3 get 🥇🥈🥉 medals; rank 4-10 get circled digits.
  * Five-tier importance emoji (🚨 🔥 ⚡ 💡 📌) instead of three.
  * Keywords render as inline ``tag`` elements (Lark 2.0), with a text fallback
    so older clients still see them as ``#kw`` text.
  * User-supplied strings pass through ``_md_escape`` so LLM output can never
    inject Markdown / HTML into the card.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.models import EvaluatedItem

# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------
# Characters that change rendering inside Lark markdown or break links.
_LARK_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#!|<>])")


def _md_escape(text: str) -> str:
    """Escape Lark markdown meta-characters in ``text``.

    We escape the chars that are dangerous at *any* position (not just line
    start): backslash, backtick, emphasis markers, brackets / parens
    (link syntax), hash, exclamation (image), pipe (table), angle brackets
    (HTML / autolink). Positional chars like ``-`` ``+`` ``.`` are left alone
    so that ``GPT-5`` doesn't render as ``GPT\-5``.
    """
    if text is None:
        return ""
    s = str(text)
    # Escape backslash first so subsequent backslashes we insert aren't doubled.
    s = s.replace("\\", "\\\\")
    return _LARK_MD_SPECIAL.sub(r"\\\1", s)


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------
_RANK_MEDALS = ("🥇", "🥈", "🥉")
_CIRCLED_DIGITS = ("0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")
_TAG_COLORS = ("blue", "green", "orange", "purple")
_MAX_TAGS = 3


def _ranking_badge(idx: int) -> str:
    """Return a medal / circled-number / plain-number prefix for rank ``idx``."""
    if 1 <= idx <= len(_RANK_MEDALS):
        return _RANK_MEDALS[idx - 1]
    if 1 <= idx <= 9:
        return _CIRCLED_DIGITS[idx]
    return f"#{idx}"


def _importance_to_indicator(importance: int) -> str:
    """Five-tier importance indicator."""
    if importance >= 9:
        return "🚨"
    if importance >= 7:
        return "🔥"
    if importance >= 5:
        return "⚡"
    if importance >= 3:
        return "💡"
    return "📌"


def _importance_to_header_color(importance: int) -> str:
    """Map importance to a Feishu header template color."""
    if importance >= 9:
        return "red"
    if importance >= 7:
        return "orange"
    if importance >= 5:
        return "blue"
    return "green"


def _format_keywords_text(keywords: list[str]) -> str:
    """Render keywords as a single line of ``#kw`` text (always present, as a
    visible fallback for clients that don't render ``tag`` elements)."""
    return " ".join(f"#{_md_escape(kw)}" for kw in keywords[:_MAX_TAGS])


def _build_tag_elements(keywords: list[str]) -> list[dict[str, Any]]:
    """Render keywords as inline Lark ``tag`` elements (text fallback included
    via the text fallback line so older clients still see ``#kw``)."""
    tags: list[dict[str, Any]] = []
    for idx, kw in enumerate(keywords[:_MAX_TAGS]):
        tags.append({
            "tag": "tag",
            "text": {
                "tag": "plain_text",
                "content": f"#{_md_escape(kw)}",
            },
            "color": _TAG_COLORS[idx % len(_TAG_COLORS)],
        })
    return tags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_card(
    items: list[EvaluatedItem],
    date: datetime,
    provider: str | None = None,
    pipeline_counts: dict[str, int] | None = None,
) -> dict:
    """Build a Feishu interactive card from evaluated news items.

    Args:
        items: Already sorted + truncated to top-N by the caller.
        date: ``datetime`` (UTC) used for the header date and footer.
        provider: AI provider label rendered in header sub-title (e.g. "deepseek").
        pipeline_counts: Optional dict ``{"fetched": 80, "deduped": 65,
            "recent": 18, "evaluated": 10}`` — used to draw a status note.

    Returns:
        Feishu ``interactive`` message body ready to POST to the webhook.
    """
    date_str = date.strftime("%Y-%m-%d")
    time_str = date.strftime("%H:%M")

    # ---- Header -----------------------------------------------------------
    if items:
        top_importance = items[0].importance
        header_color = _importance_to_header_color(top_importance)
        title = f"AI 资讯速递 · {date_str} · 共 {len(items)} 条"
    else:
        header_color = "grey"
        title = f"AI 资讯速递 · {date_str} · 暂无更新"

    header: dict[str, Any] = {
        "template": header_color,
        "title": {
            "tag": "plain_text",
            "content": title,
        },
    }
    if provider:
        header["sub_title"] = {
            "tag": "plain_text",
            "content": f"by {provider}",
        }

    # ---- Body -------------------------------------------------------------
    elements: list[dict[str, Any]] = []

    if not items:
        elements.append({
            "tag": "markdown",
            "content": _md_escape("今日暂无重要 AI 新闻,明天见～"),
        })
    else:
        for idx, item in enumerate(items, 1):
            badge = _ranking_badge(idx)
            indicator = _importance_to_indicator(item.importance)
            safe_title = _md_escape(item.title)
            # URL must NOT be escaped — it goes inside Markdown link syntax
            # and escaping the dots / etc. would break the link target.
            raw_url = item.url if item.url else ""
            safe_summary = _md_escape(item.chinese_summary)
            safe_source = _md_escape(item.source)
            kw_fallback = _format_keywords_text(item.keywords)

            if raw_url:
                link_md = f"[🔗 阅读原文]({raw_url})"
            else:
                link_md = "<font color='grey'>🔗 链接不可用</font>"

            line1 = f"{badge} **{safe_title}**  {indicator} {item.importance}/10"
            line2 = f"📰 {safe_source}  •  {link_md}"
            line3 = f"\n{safe_summary}" if safe_summary else ""
            line4 = f"\n{kw_fallback}" if kw_fallback else ""

            content_md = f"{line1}\n{line2}{line3}{line4}"

            column_elements: list[dict[str, Any]] = [
                {"tag": "markdown", "content": content_md}
            ]
            # NOTE: inline `tag` elements (Lark 2.0 card JSON) are omitted
            # because many Feishu webhooks reject them with
            # "unsupported type of block; ErrorValue: tag".
            # The keywords are already rendered as `#kw` text in the
            # markdown block above, so nothing is lost visually.

            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": column_elements,
                    }
                ],
            })

            if idx < len(items):
                elements.append({"tag": "hr"})

    # ---- Footer / pipeline note ------------------------------------------
    if pipeline_counts:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": (
                        f"📊 抓取 {pipeline_counts.get('fetched', 0)} → "
                        f"去重 {pipeline_counts.get('deduped', 0)} → "
                        f"近 24h {pipeline_counts.get('recent', 0)} → "
                        f"入选 {pipeline_counts.get('evaluated', 0)} 条"
                    ),
                }
            ],
        })

    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": f"⏱ 报告生成于 {time_str} UTC"}
        ],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": header,
            "elements": elements,
        },
    }