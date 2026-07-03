"""Cog 공통 베이스: 주입 의존성 + 응답/권한 검증 헬퍼."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

from ..config import Settings
from ..player.guild_player import GuildPlayer
from ..player.registry import PlayerRegistry
from ..ui.embeds import EmbedFactory

logger = logging.getLogger(__name__)


class MusicCog(commands.Cog):
    def __init__(
        self, bot: commands.Bot, registry: PlayerRegistry, embeds: EmbedFactory,
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.registry = registry
        self.embeds = embeds
        self.settings = settings

    def connected_player(self, interaction: discord.Interaction) -> Optional[GuildPlayer]:
        """연결된 플레이어를 반환. 없으면 None."""
        player = self.registry.get(interaction.guild.id)
        if player and player.is_connected():
            return player
        return None

    async def respond(
        self, interaction: discord.Interaction, embed: discord.Embed,
        *, ephemeral: bool = False,
    ) -> None:
        """최초 응답/후속 전송을 자동 분기해 안전하게 응답한다."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except discord.HTTPException as exc:
            logger.warning("응답 전송 실패 - %s", exc)

    async def warn(self, interaction: discord.Interaction, msg: str) -> None:
        await self.respond(interaction, self.embeds.warning(msg), ephemeral=True)

    async def require_player(
        self, interaction: discord.Interaction,
    ) -> Optional[GuildPlayer]:
        """봇이 연결돼 있으면 플레이어 반환, 아니면 경고 후 None (조회 명령용)."""
        player = self.connected_player(interaction)
        if player is None:
            await self.warn(interaction, "봇이 음성 채널에 없습니다.")
        return player

    async def require_control(
        self, interaction: discord.Interaction,
    ) -> Optional[GuildPlayer]:
        """재생 제어용: 봇 연결 + 사용자가 봇과 같은 음성 채널이어야 한다."""
        player = await self.require_player(interaction)
        if player is None:
            return None
        voice = getattr(interaction.user, "voice", None)
        channel = voice.channel if voice else None
        if channel is None or channel != player.voice_channel:
            await self.warn(interaction, "봇과 같은 음성 채널에 있어야 사용할 수 있는 명령어입니다.")
            return None
        return player
