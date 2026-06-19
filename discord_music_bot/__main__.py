"""봇 진입점: python -m discord_music_bot."""

from __future__ import annotations

import logging

import discord

from .bot import build_bot
from .config import Settings
from .logging_setup import configure_logging

logger = logging.getLogger("discord.bot.main")


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if not settings.bot_token:
        print("\n  ✗ 오류: BOT_TOKEN 환경 변수가 설정되지 않았습니다.\n")
        logger.critical("BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
        return

    bot = build_bot(settings)
    logger.info("봇 시작 중...")
    try:
        bot.run(settings.bot_token, log_handler=None)
    except discord.LoginFailure:
        logger.critical("로그인 실패. BOT_TOKEN을 확인해주세요.")
    except Exception as exc:  # noqa: BLE001
        logger.critical("봇 실행 중 오류 발생 - %s", exc, exc_info=True)


if __name__ == "__main__":
    main()
