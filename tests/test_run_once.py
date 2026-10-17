from types import SimpleNamespace
from unittest.mock import patch

import run_once


def test_main_returns_pipeline_exit_code():
    with (
        patch("run_once.load_config", return_value=SimpleNamespace()),
        patch("run_once.setup_logging"),
        patch("run_once.validate_runtime_config"),
        patch(
            "run_once.run_daily_digest",
            return_value=SimpleNamespace(exit_code=1),
        ),
    ):
        assert run_once.main([]) == 1


def test_dry_run_validates_without_publish_and_skips_delivery():
    config = SimpleNamespace()
    with (
        patch("run_once.load_config", return_value=config),
        patch("run_once.setup_logging"),
        patch("run_once.validate_runtime_config") as validate,
        patch(
            "run_once.run_daily_digest",
            return_value=SimpleNamespace(exit_code=0),
        ) as run,
    ):
        assert run_once.main(["--dry-run"]) == 0

    validate.assert_called_once_with(config, publish=False)
    run.assert_called_once_with(config, dry_run=True)
