"""로깅 설정 분리. main 진입점에서 1회 호출한다."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s:%(lineno)d] %(message)s",
    )
    for noisy in ("discord", "discord.gateway", "discord.client", "discord.http"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
