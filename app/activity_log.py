"""슬래시 명령 활동을 한국어로 기록하는 관찰자(observer).

모든 명령에 공통인 '호출 결과 + 인자' 로깅을 한곳에 모아(SRP·DRY), 각 Cog 명령
핸들러가 로깅 코드를 중복하지 않게 한다. 새 명령을 추가해도 로깅 코드는 손대지
않는다(OCP). 포맷 헬퍼는 순수 함수라 단위 테스트가 쉽다.

discord.py의 `interaction_check`는 command/namespace가 채워지기 전에 호출되므로
명령 로깅에 쓸 수 없다. 대신 둘 다 채워진 뒤인 `on_app_command_completion`
(성공)과 `on_app_command_error`(실패) 시점에 기록한다.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


def format_command_args(interaction: discord.Interaction) -> str:
    """명령 인자를 ` (key=value, ...)` 형태 문자열로 만든다. 없으면 빈 문자열."""
    namespace = getattr(interaction, "namespace", None)
    data = vars(namespace) if namespace is not None else {}
    if not data:
        return ""
    return " (" + ", ".join(f"{key}={value!r}" for key, value in data.items()) + ")"


def command_context(interaction: discord.Interaction) -> tuple[str, str, str]:
    """상호작용에서 (길드명, 명령명, 사용자명)을 안전하게 추출한다."""
    guild = interaction.guild.name if interaction.guild else "DM"
    command = interaction.command
    name = command.name if command else "알 수 없음"
    user = getattr(interaction.user, "name", "알 수 없음")
    return guild, name, user


def register_command_logging(bot: commands.Bot) -> None:
    """모든 슬래시 명령의 성공 완료를 한국어로 기록하는 리스너를 등록한다."""

    async def on_app_command_completion(
        interaction: discord.Interaction, command: discord.app_commands.Command
    ) -> None:
        guild, _name, user = command_context(interaction)
        logger.info(
            "[%s] /%s 완료 - 사용자: %s%s",
            guild, command.name, user, format_command_args(interaction),
        )

    bot.add_listener(on_app_command_completion, "on_app_command_completion")
