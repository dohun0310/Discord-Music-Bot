"""Cog 공통 베이스: 주입 의존성 + 음성/플레이어 사전 확인 헬퍼."""

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

from ..config import Settings
from ..player.guild_player import GuildPlayer
from ..player.registry import PlayerRegistry
from ..ui.embeds import EmbedFactory


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
        """연결된 플레이어를 반환. 없으면 None (호출 측에서 경고 응답)."""
        player = self.registry.get(interaction.guild.id)
        if player and player.is_connected():
            return player
        return None

    async def warn_no_player(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=self.embeds.warning("봇이 음성 채널에 없습니다."), ephemeral=True
        )
