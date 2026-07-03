"""Unified configuration loader from .env and config.yaml."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


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
    with open(yaml_path, "r", encoding="utf-8") as f:
        yaml_config = yaml.safe_load(f)

    return Config(
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
