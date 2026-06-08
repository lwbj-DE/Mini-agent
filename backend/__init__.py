"""Mini Agent backend package.

Imports this package to trigger Loguru configuration (once at startup).
"""

import sys

from loguru import logger

from .config import get_config

# Remove default Loguru handler
logger.remove()

# Console: colorized, debug level in dev
logger.add(
    sys.stderr,
    level="DEBUG",
    colorize=True,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <7}</level> | "
        "<level>{message}</level>"
    ),
)

# File: daily rotation, 7-day retention, zipped, async
cfg = get_config()
logger.add(
    str(cfg.logs_dir + "/app_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    rotation="00:00",
    retention="7 days",
    compression="zip",
    encoding="utf-8",
    enqueue=True,
)

logger.info(f"Loguru configured — logs → {cfg.logs_dir}")
