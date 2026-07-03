"""AI News Daily Digest — main entry point with scheduler."""
from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.config import load_config
from src.logger import setup_logging
from src.scheduler import run_daily_digest

# One-shot event to break the main thread out of ``wait()`` on shutdown.
_shutdown_event = threading.Event()


def main() -> None:
    project_root = Path(__file__).parent
    config = load_config(str(project_root))
    setup_logging(config, str(project_root / "logs"))

    schedule = config.schedule
    hour = schedule.get("cron_hour", 2)
    minute = schedule.get("cron_minute", 0)

    logger.info(
        f"AI News Daily Digest starting. "
        f"Scheduled: {hour:02d}:{minute:02d} daily"
    )

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_digest,
        trigger=CronTrigger(hour=hour, minute=minute),
        args=[config],
        id="daily_digest",
        name="AI News Daily Digest",
    )
    scheduler.start()

    def shutdown(_sig, _frame):
        logger.info("Shutting down scheduler...")
        _shutdown_event.set()
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Block until shutdown signal — no busy-loop, works on Windows & Unix.
    _shutdown_event.wait()


if __name__ == "__main__":
    main()