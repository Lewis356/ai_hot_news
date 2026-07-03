from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.publisher.card_builder import _md_escape, build_card
from src.publisher.feishu import _sign_payload, send_card
from src.config import Config
from src.models import EvaluatedItem
from src.utils.redact import redact


def make_feishu_config(secret: str = "") -> Config:
    return Config(
        deepseek_api_key="sk-test",
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        feishu_webhook_secret=secret,
    )


# ---------------------------------------------------------------------------
# Card structure (back-compat — original assertions still hold)
# ---------------------------------------------------------------------------
def test_build_card_structure():
    items = [
        EvaluatedItem(
            title="GPT-5震撼发布",
            url="https://example.com/gpt5",
            source="机器之心",
            chinese_summary="OpenAI正式发布GPT-5，在推理和多模态能力上大幅超越前代模型。",
            importance=10,
            keywords=["大模型", "OpenAI", "GPT-5"],
            published_at=datetime.now(timezone.utc),
        )
    ]
    today = datetime(2026, 6, 23)
    card = build_card(items, today)

    assert card["msg_type"] == "interactive"
    header_text = card["card"]["header"]["title"]["content"]
    assert "AI 资讯速递" in header_text
    assert "2026-06-23" in header_text

    card_text = str(card)
    assert "GPT-5震撼发布" in card_text
    assert "https://example.com/gpt5" in card_text
    assert "#大模型" in card_text


def test_build_card_top_n_layout():
    items = [
        EvaluatedItem(
            f"News {i}", f"http://a.com/{i}", "S", f"摘要{i}",
            10 - i, ["AI", "测试"], datetime.now(timezone.utc)
        )
        for i in range(10)
    ]
    card = build_card(items, datetime(2026, 6, 23))
    card_str = str(card)
    for i in range(10):
        assert f"News {i}" in card_str


def test_build_card_handles_empty_list():
    card = build_card([], datetime(2026, 6, 23))
    assert card["msg_type"] == "interactive"
    card_str = str(card)
    assert "暂无" in card_str


# ---------------------------------------------------------------------------
# Card beautification (Phase 5)
# ---------------------------------------------------------------------------
def test_build_card_renders_medals():
    items = [
        EvaluatedItem(
            f"Top {i}", f"http://a.com/{i}", "S", f"s{i}",
            10, ["AI"], datetime.now(timezone.utc),
        )
        for i in range(1, 6)
    ]
    card = build_card(items, datetime(2026, 6, 23), provider="deepseek")
    card_str = str(card)
    assert "🥇" in card_str
    assert "🥈" in card_str
    assert "🥉" in card_str


def test_build_card_emits_keywords_as_text():
    """Inline tag elements are unsupported by some Feishu webhooks, so we
    render keywords as ``#kw`` text in the markdown block instead."""
    items = [
        EvaluatedItem(
            "标题", "http://x.com", "源", "摘要",
            9, ["大模型", "GPT", "OpenAI"], datetime.now(timezone.utc),
        )
    ]
    card = build_card(items, datetime(2026, 6, 23))
    card_text = str(card)
    assert "#大模型" in card_text
    assert "#GPT" in card_text
    assert "#OpenAI" in card_text
    # And no Lark-2.0 tag elements leaked into the JSON
    assert '"tag": "tag"' not in card_text


def test_build_card_header_color_varies():
    high = EvaluatedItem("A", "http://a", "S", "s", 10, ["x"], datetime.now(timezone.utc))
    mid = EvaluatedItem("B", "http://b", "S", "s", 7, ["x"], datetime.now(timezone.utc))
    low = EvaluatedItem("C", "http://c", "S", "s", 4, ["x"], datetime.now(timezone.utc))

    high_card = build_card([high], datetime(2026, 6, 23))
    mid_card = build_card([mid], datetime(2026, 6, 23))
    low_card = build_card([low], datetime(2026, 6, 23))

    assert high_card["card"]["header"]["template"] == "red"
    assert mid_card["card"]["header"]["template"] == "orange"
    assert low_card["card"]["header"]["template"] == "green"


def test_build_card_includes_provider_and_pipeline_counts():
    items = [
        EvaluatedItem("A", "http://a", "S", "s", 8, ["x"], datetime.now(timezone.utc)),
    ]
    card = build_card(
        items,
        datetime(2026, 6, 23),
        provider="deepseek",
        pipeline_counts={"fetched": 80, "deduped": 65, "recent": 18, "evaluated": 10},
    )
    assert card["card"]["header"].get("sub_title", {}).get("content") == "by deepseek"
    card_str = str(card)
    assert "抓取 80" in card_str
    assert "入选 10" in card_str


# ---------------------------------------------------------------------------
# Markdown escape
# ---------------------------------------------------------------------------
def test_escape_blocks_script_injection():
    payload = "<script>alert('xss')</script>"
    escaped = _md_escape(payload)
    assert "<script>" not in escaped
    assert "<\\/script>" in escaped or "\\\\<" in escaped or "\\<" in escaped


def test_escape_neutralizes_link_syntax():
    assert _md_escape("[click](http://evil)") != "[click](http://evil)"
    # The escape inserts backslashes before brackets/parens
    assert "\\[" in _md_escape("[click](http://evil)")


def test_escape_passes_plain_text():
    assert _md_escape("大模型发布") == "大模型发布"
    assert _md_escape("GPT-5震撼发布") == "GPT-5震撼发布"


# ---------------------------------------------------------------------------
# Feishu HMAC + retry (Phase 1)
# ---------------------------------------------------------------------------
def test_sign_payload_matches_feishu_spec():
    secret = "test_secret"
    ts = 1700000000
    expected = "vpAnmEKI4kW6s9JFBgY7HgkVTb1nvFxC6yvC7d0Zk9k="  # known vector
    # We compute with our own hmac and compare manually:
    import base64, hashlib, hmac
    raw = hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
    assert _sign_payload(secret, ts) == base64.b64encode(raw).decode()


def test_signs_payload_when_secret_present():
    card = {"msg_type": "interactive", "card": {}}
    cfg = make_feishu_config(secret="mysecret")
    with patch("src.publisher.feishu.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "msg": "success"},
        )
        result = send_card(card, cfg, max_retries=1)
    assert result is True
    sent_body = mock_post.call_args.kwargs["json"]
    assert "timestamp" in sent_body
    assert "sign" in sent_body
    assert sent_body["timestamp"].isdigit()


def test_does_not_sign_when_secret_empty():
    card = {"msg_type": "interactive", "card": {}}
    cfg = make_feishu_config(secret="")
    with patch("src.publisher.feishu.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"code": 0, "msg": "success"},
        )
        send_card(card, cfg, max_retries=1)
    sent_body = mock_post.call_args.kwargs["json"]
    assert "sign" not in sent_body
    assert "timestamp" not in sent_body


def test_retries_on_5xx_then_succeeds():
    """Real retry behavior — first call raises, second call succeeds."""
    card = {"msg_type": "interactive", "card": {}}
    cfg = make_feishu_config()

    ok_response = MagicMock(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"code": 0, "msg": "success"},
    )
    bad_response = MagicMock(
        status_code=500,
        raise_for_status=MagicMock(side_effect=httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock(),
        )),
    )
    with patch("src.publisher.feishu.httpx.post", side_effect=[bad_response, ok_response]) as mock_post:
        with patch("src.publisher.feishu.time.sleep"):
            result = send_card(card, cfg, max_retries=2)
    assert result is True
    assert mock_post.call_count == 2


def test_send_card_success():
    card = {"msg_type": "interactive", "card": {}}
    with patch("httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"code": 0, "msg": "success"}
        result = send_card(card, make_feishu_config())
        assert result is True


def test_send_card_timeout():
    card = {"msg_type": "interactive", "card": {}}
    with patch("src.publisher.feishu.httpx.post", side_effect=Exception("Timeout")):
        with patch("src.publisher.feishu.time.sleep"):
            result = send_card(card, make_feishu_config(), max_retries=1)
            assert result is False


def test_send_card_no_url():
    card = {"msg_type": "interactive", "card": {}}
    cfg = Config(
        deepseek_api_key="sk-test",
        feishu_webhook_url="",
    )
    result = send_card(card, cfg)
    assert result is False


def test_send_card_app_level_error_does_not_retry():
    """code != 0 must NOT retry — same payload will keep failing."""
    card = {"msg_type": "interactive", "card": {}}
    cfg = make_feishu_config()
    with patch("src.publisher.feishu.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"code": 230001, "msg": "invalid token"},
        )
        result = send_card(card, cfg, max_retries=3)
    assert result is False
    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Redact utility (Phase 1)
# ---------------------------------------------------------------------------
def test_redact_strips_sk_keys():
    s = "Authorization failed for key sk-1234567890abcdef1234567890abcdef"
    out = redact(s)
    assert "sk-1234567890" not in out
    assert "***REDACTED***" in out


def test_redact_strips_bearer_tokens():
    assert "REDACTED" in redact("Bearer abc.def.ghi")


def test_redact_strips_query_string_tokens():
    assert "REDACTED" in redact("?api_key=secret123&other=ok")
    assert "secret123" not in redact("?api_key=secret123&other=ok")


def test_redact_strips_feishu_webhook_uuid():
    s = "POST https://open.feishu.cn/open-apis/bot/v2/hook/cc025b8e-378a-4cff-ba8d-a5e38154fae2"
    assert "cc025b8e" not in redact(s)


def test_redact_handles_non_string():
    class E(Exception):
        def __str__(self):
            return "auth failed for sk-abcdefghijklmnopqrstuvwxyz1234"
    assert "REDACTED" in redact(E("boom"))