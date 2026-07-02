"""텍스트 채널 알림 전송. 실패를 삼키고 로깅해 재생 루프를 보호한다."""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger(__name__)


class ChannelNotifier:
    def __init__(self, channel: discord.abc.Messageable, *, guild_name: str) -> None:
        self._channel = channel
        self._guild_name = guild_name

    @property
    def channel(self) -> discord.abc.Messageable:
        return self._channel

    def set_channel(self, channel: discord.abc.Messageable) -> None:
        self._channel = channel

    async def send(self, embed: discord.Embed) -> bool:
        """임베드 전송. 실패 시 경고 로깅 후 False (예외를 전파하지 않음)."""
        try:
            await self._channel.send(embed=embed)
            return True
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 재생을 막으면 안 됨
            logger.warning("[%s] 채널 알림 전송 실패 - %s", self._guild_name, exc)
            return False
