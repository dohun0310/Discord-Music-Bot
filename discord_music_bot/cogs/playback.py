"""재생 계열 명령: /재생 /스킵 /정지 /일시정지 /재개 /현재곡."""

from __future__ import annotations

import logging

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from ..config import Emoji, Settings
from ..player.registry import PlayerRegistry
from ..services.resolver import PlaylistResolution, TrackResolver
from ..ui.embeds import EmbedFactory
from ..ui.formatting import truncate_string
from .base import MusicCog

logger = logging.getLogger("discord.bot.cog.playback")


class PlaybackCog(MusicCog):
    def __init__(
        self, bot: commands.Bot, registry: PlayerRegistry, embeds: EmbedFactory,
        settings: Settings, resolver: TrackResolver,
    ) -> None:
        super().__init__(bot, registry, embeds, settings)
        self.resolver = resolver

    @app_commands.command(name="재생", description="YouTube에서 노래/플레이리스트를 재생합니다.")
    @app_commands.describe(query="재생할 노래/플레이리스트의 제목 또는 URL")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        # 1) 사전 확인: 사용자가 음성 채널에 있는가 (defer 이전, 즉시 응답)
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=self.embeds.warning("먼저 음성 채널에 접속해주세요."), ephemeral=True
            )
            return
        channel = interaction.user.voice.channel

        await interaction.response.defer(thinking=True)

        # 2) 플레이어 확보 (연결)
        player = self.registry.get(interaction.guild.id)
        if player is None or not player.is_connected():
            try:
                if player:
                    await player.destroy(notify=False)
                voice_client = await channel.connect()
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] 음성 연결 실패 - %s", interaction.guild.name, exc, exc_info=True)
                await interaction.followup.send(
                    embed=self.embeds.error(f"음성 채널 연결 실패: {exc}")
                )
                return
            player = self.registry.create(
                guild=interaction.guild, text_channel=interaction.channel,
                voice_client=voice_client,
            )
        else:
            player.text_channel = interaction.channel

        # 3) 해석
        try:
            result = await self.resolver.resolve(query, interaction.user.mention)
        except yt_dlp.utils.DownloadError as exc:
            await interaction.followup.send(embed=self.embeds.error(self._download_error_message(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] 정보 검색 실패 - %s", interaction.guild.name, exc, exc_info=True)
            await interaction.followup.send(embed=self.embeds.error(f"음악 정보를 가져오는 중 오류 발생: {exc}"))
            return

        if result is None:
            await interaction.followup.send(embed=self.embeds.error("검색 결과가 없거나 처리 중 오류가 발생했습니다."))
            return

        # 4) 대기열 추가
        if isinstance(result, PlaylistResolution):
            player.set_playlist(result.original_url, result.next_start_index, interaction.user.mention)
            count = player.add_tracks(result.tracks)
            if count == 0:
                await interaction.followup.send(
                    embed=self.embeds.warning(f"플레이리스트 '{result.title}'에서 유효한 곡을 찾지 못했습니다.")
                )
                return
            await interaction.followup.send(
                embed=self.embeds.playlist_added(result.title, count=count, requester=interaction.user.mention)
            )
        else:
            player.add_track(result.track)
            await interaction.followup.send(
                embed=self.embeds.track_added(result.track, queue_position=player.queue_size)
            )

    @staticmethod
    def _download_error_message(exc: Exception) -> str:
        text = str(exc)
        if "is not available" in text or "Private video" in text:
            return "해당 영상을 찾을 수 없거나 비공개 영상입니다."
        if "Unsupported URL" in text:
            return "지원하지 않는 URL 형식입니다."
        return f"영상을 가져오는 중 오류 발생: {exc}"

    @app_commands.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        skipped = player.skip()
        if skipped is None:
            await interaction.response.send_message(
                embed=self.embeds.warning("재생 중인 곡이 없습니다."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=self.embeds.success(f"**{truncate_string(skipped.title, 40)}** 건너뛰었습니다.")
        )

    @app_commands.command(name="정지", description="음악 재생을 중지하고 봇을 퇴장시킵니다.")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        await player.destroy(notify=False)
        await interaction.response.send_message(
            embed=self.embeds.message(f"{Emoji.STOP} 음악 재생을 중지하고 연결을 종료했습니다.")
        )

    @app_commands.command(name="일시정지", description="음악 재생을 일시정지합니다.")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        if await player.pause():
            await interaction.response.send_message(embed=self.embeds.message(f"{Emoji.PAUSE} 일시정지되었습니다."))
        else:
            await interaction.response.send_message(
                embed=self.embeds.warning("재생 중인 곡이 없습니다."), ephemeral=True
            )

    @app_commands.command(name="재개", description="일시정지된 음악을 다시 재생합니다.")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        if await player.resume():
            await interaction.response.send_message(embed=self.embeds.success("재생을 재개합니다."))
        else:
            await interaction.response.send_message(
                embed=self.embeds.warning("일시정지된 곡이 없습니다."), ephemeral=True
            )

    @app_commands.command(name="현재곡", description="현재 재생 중인 곡 정보를 표시합니다.")
    @app_commands.guild_only()
    async def now_playing(self, interaction: discord.Interaction) -> None:
        player = self.connected_player(interaction)
        if not player:
            await self.warn_no_player(interaction)
            return
        if not player.current:
            await interaction.response.send_message(
                embed=self.embeds.warning("현재 재생 중인 곡이 없습니다."), ephemeral=True
            )
            return
        await interaction.response.defer()
        embed = self.embeds.progress(
            player.current, volume=player.volume, repeat_mode=player.repeat_mode,
            queue_size=player.queue_size, position=player.playback_position(),
        )
        await interaction.followup.send(embed=embed)
