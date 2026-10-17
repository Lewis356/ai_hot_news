"""Run the daily digest once (for manual testing / debugging)."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_config, validate_runtime_config
from src.logger import setup_logging
from src.scheduler import run_daily_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AI news digest once")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and evaluate without sending a Feishu message",
    )
    args = parser.parse_args(argv)

    project_root = Path(__file__).parent
    config = load_config(str(project_root))
    setup_logging(config, str(project_root / "logs"))
    validate_runtime_config(config, publish=not args.dry_run)
    result = run_daily_digest(config, dry_run=args.dry_run)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
