"""Logging configuration using loguru."""
import sys
from pathlib import Path
from loguru import logger as loguru_logger


def setup_logging(config, log_dir: str = "logs") -> None:
    """Configure loguru to output to both console and file."""
    loguru_logger.remove()

    # Console output (INFO, colored)
    loguru_logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
        level="INFO",
        colorize=True,
    )

    # File output (DEBUG, daily rotation, retention)
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    retention = config.logging.get("retention_days", 30)
    loguru_logger.add(
        log_path / "daily_{time:YYYY-MM-DD}.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        level="DEBUG",
        rotation="00:00",
        retention=f"{retention} days",
        encoding="utf-8",
    )

    loguru_logger.debug("Logging initialized")
