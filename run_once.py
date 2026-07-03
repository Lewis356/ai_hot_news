"""Run the daily digest once (for manual testing / debugging)."""
from pathlib import Path
from src.config import load_config
from src.logger import setup_logging
from src.scheduler import run_daily_digest


def main():
    project_root = Path(__file__).parent
    config = load_config(str(project_root))
    setup_logging(config, str(project_root / "logs"))
    run_daily_digest(config)


if __name__ == "__main__":
    main()
