from __future__ import annotations

import pytest

from src.config import (
    Config,
    ConfigError,
    validate_config_structure,
    validate_runtime_config,
)


def make_config(**overrides) -> Config:
    values = {
        "deepseek_api_key": "sk-test",
        "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "feishu_webhook_secret": "secret",
        "rss_sources": [{"name": "Test", "url": "https://example.com/feed"}],
        "schedule": {"cron_hour": 0, "cron_minute": 7, "timezone": "Asia/Shanghai"},
        "ai": {"provider": "deepseek", "top_n": 10, "max_candidates": 60},
        "dedup": {"title_similarity_threshold": 0.8},
    }
    values.update(overrides)
    return Config(**values)


def test_runtime_config_requires_selected_provider_key():
    config = make_config(deepseek_api_key="")

    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        validate_runtime_config(config, publish=True)


def test_runtime_config_allows_unsigned_webhook_for_publish():
    config = make_config(feishu_webhook_secret="")

    validate_runtime_config(config, publish=True)


def test_runtime_config_requires_webhook_url_for_publish():
    config = make_config(feishu_webhook_url="", feishu_webhook_secret="")

    with pytest.raises(ConfigError, match="FEISHU_WEBHOOK_URL"):
        validate_runtime_config(config, publish=True)


def test_dry_run_does_not_require_feishu_credentials():
    config = make_config(feishu_webhook_url="", feishu_webhook_secret="")

    validate_runtime_config(config, publish=False)


def test_config_rejects_invalid_timezone():
    config = make_config(
        schedule={"cron_hour": 0, "cron_minute": 7, "timezone": "Mars/Olympus"}
    )

    with pytest.raises(ConfigError, match="timezone"):
        validate_config_structure(config)


def test_config_rejects_top_n_larger_than_candidate_limit():
    config = make_config(
        ai={"provider": "deepseek", "top_n": 20, "max_candidates": 10}
    )

    with pytest.raises(ConfigError, match="top_n"):
        validate_config_structure(config)
