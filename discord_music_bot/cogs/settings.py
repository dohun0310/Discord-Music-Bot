"""설정 계열 명령: /볼륨 /반복."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from ..config import Emoji
from ..domain.models import RepeatMode
from .base import MusicCog

logger = logging.getLogger("discord.bot.cog.settings")


class SettingsCog(MusicCog):
    @app_commands.command(name="볼륨", description="볼륨을 조절합니다. (0-200%)")
    @app_commands.describe(volume="볼륨 (0-200)")
    @app_commands.guild_only()
    async def volume(
        self, interaction: discord.Interaction, volume: app_commands.Range[int, 0, 200]
    ) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        new_volume = player.set_volume(volume / 100)
        if new_volume == 0:
            emoji = Emoji.VOLUME_MUTE
        elif new_volume < 0.5:
            emoji = Emoji.VOLUME_LOW
        else:
            emoji = Emoji.VOLUME_HIGH
        await interaction.response.send_message(
            embed=self.embeds.message(f"{emoji} 볼륨: **{new_volume:.0%}**")
        )

    @app_commands.command(name="반복", description="반복 재생 모드를 변경합니다.")
    @app_commands.guild_only()
    async def repeat(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        mode = player.toggle_repeat()
        if mode == RepeatMode.OFF:
            msg = f"{Emoji.REPEAT} 반복 재생이 **꺼졌습니다**"
        elif mode == RepeatMode.ALL:
            msg = f"{Emoji.REPEAT} **전체 반복** 모드가 켜졌습니다"
        else:
            msg = f"{Emoji.REPEAT_ONE} **한 곡 반복** 모드가 켜졌습니다"
        await interaction.response.send_message(embed=self.embeds.message(msg))
