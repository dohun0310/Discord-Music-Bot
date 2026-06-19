"""대기열 계열 명령: /대기열 /삭제 /비우기 /셔플."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from ..config import Emoji
from ..ui.formatting import truncate_string
from .base import MusicCog

logger = logging.getLogger(__name__)


class QueueCog(MusicCog):
    @app_commands.command(name="대기열", description="현재 재생 대기열을 확인합니다.")
    @app_commands.guild_only()
    async def show_queue(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        await interaction.response.defer()
        embed = self.embeds.queue(
            current=player.current, position=player.playback_position(),
            paused=player.paused, snapshot=player.snapshot(), volume=player.volume,
            repeat_mode=player.repeat_mode,
            max_display=self.settings.max_queue_display,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
    @app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
    @app_commands.guild_only()
    async def remove(
        self, interaction: discord.Interaction, position: app_commands.Range[int, 1]
    ) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        await interaction.response.defer()
        try:
            removed = player.remove(position)
        except IndexError:
            await interaction.followup.send(
                embed=self.embeds.warning(f"유효하지 않은 순번입니다. (최대: {player.queue_size})")
            )
            return
        await interaction.followup.send(
            embed=self.embeds.success(f"**{truncate_string(removed.title, 40)}** 제거되었습니다.")
        )

    @app_commands.command(name="비우기", description="대기열을 비웁니다.")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        count = player.clear_queue()
        if count > 0:
            await interaction.response.send_message(
                embed=self.embeds.success(f"대기열에서 **{count}곡**을 제거했습니다.")
            )
        else:
            await interaction.response.send_message(
                embed=self.embeds.warning("대기열이 이미 비어있습니다."), ephemeral=True
            )

    @app_commands.command(name="셔플", description="대기열을 섞습니다.")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        count = player.shuffle_queue()
        if count > 0:
            await interaction.response.send_message(
                embed=self.embeds.success(f"{Emoji.SHUFFLE} 대기열의 **{count}곡**을 섞었습니다.")
            )
        else:
            await interaction.response.send_message(
                embed=self.embeds.warning("대기열에 곡이 부족합니다."), ephemeral=True
            )
