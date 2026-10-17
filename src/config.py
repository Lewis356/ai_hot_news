"""Unified configuration loader from .env and config.yaml."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when runtime configuration cannot execute safely."""


@dataclass
class Config:
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = ""
    feishu_webhook_url: str = ""
    feishu_webhook_secret: str = ""
    rss_sources: list[dict] = field(default_factory=list)
    schedule: dict = field(default_factory=dict)
    ai: dict = field(default_factory=dict)
    dedup: dict = field(default_factory=dict)
    logging: dict = field(default_factory=dict)


def validate_config_structure(config: Config) -> None:
    """Reject invalid static settings before any network work starts."""
    if not config.rss_sources:
        raise ConfigError("At least one RSS source is required")
    names: set[str] = set()
    for source in config.rss_sources:
        name = str(source.get("name", "")).strip()
        url = str(source.get("url", "")).strip()
        if not name or name in names:
            raise ConfigError("RSS source names must be non-empty and unique")
        if urlparse(url).scheme not in {"http", "https"}:
            raise ConfigError(f"RSS source '{name}' must use an HTTP(S) URL")
        names.add(name)

    hour = config.schedule.get("cron_hour", 0)
    minute = config.schedule.get("cron_minute", 7)
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ConfigError("schedule.cron_hour must be between 0 and 23")
    if not isinstance(minute, int) or not 0 <= minute <= 59:
        raise ConfigError("schedule.cron_minute must be between 0 and 59")
    timezone_name = config.schedule.get("timezone", "Asia/Shanghai")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        raise ConfigError(f"Invalid schedule timezone: {timezone_name}") from None

    top_n = config.ai.get("top_n", 10)
    max_candidates = config.ai.get("max_candidates", 60)
    if not isinstance(top_n, int) or top_n < 1:
        raise ConfigError("ai.top_n must be a positive integer")
    if not isinstance(max_candidates, int) or max_candidates < top_n:
        raise ConfigError("ai.max_candidates must be greater than or equal to ai.top_n")

    threshold = config.dedup.get("title_similarity_threshold", 0.8)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ConfigError("dedup.title_similarity_threshold must be between 0 and 1")


def validate_runtime_config(config: Config, *, publish: bool) -> None:
    """Validate credentials and settings required for one pipeline run."""
    provider = config.ai.get("provider", "deepseek")
    if provider == "deepseek" and not config.deepseek_api_key:
        raise ConfigError("DEEPSEEK_API_KEY is required for provider=deepseek")
    if provider == "openai" and not config.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is required for provider=openai")
    if provider == "ollama" and not config.ollama_base_url:
        raise ConfigError("OLLAMA_BASE_URL is required for provider=ollama")
    if provider not in {"deepseek", "openai", "ollama", "rule"}:
        raise ConfigError(f"Unsupported AI provider: {provider}")
    if not config.rss_sources:
        raise ConfigError("At least one RSS source is required")

    if publish:
        if not config.feishu_webhook_url:
            raise ConfigError("FEISHU_WEBHOOK_URL is required for publishing")
        if not config.feishu_webhook_secret:
            raise ConfigError("FEISHU_WEBHOOK_SECRET is required for publishing")


def load_config(config_dir: str = ".") -> Config:
    """Load configuration from .env and config.yaml in the given directory."""
    base = Path(config_dir)

    # Load .env
    env_path = base / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv(base / ".." / ".env")

    # Load config.yaml
    yaml_path = base / "config.yaml"
    if not yaml_path.exists():
        yaml_path = base / ".." / "config.yaml"
    with open(yaml_path, encoding="utf-8") as f:
        yaml_config = yaml.safe_load(f)

    config = Config(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", ""),
        feishu_webhook_secret=os.getenv("FEISHU_WEBHOOK_SECRET", ""),
        rss_sources=yaml_config.get("rss_sources", []),
        schedule=yaml_config.get("schedule", {}),
        ai=yaml_config.get("ai", {}),
        dedup=yaml_config.get("dedup", {}),
        logging=yaml_config.get("logging", {}),
    )
    validate_config_structure(config)
    return config
