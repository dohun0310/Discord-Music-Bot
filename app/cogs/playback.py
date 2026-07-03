"""재생 계열 명령: /재생 /스킵 /정지 /일시정지 /재개 /현재곡."""

from __future__ import annotations

import logging

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from ..config import Settings
from ..player.registry import PlayerRegistry
from ..services.resolver import PlaylistResolution, TrackResolver
from ..ui.embeds import EmbedFactory
from ..ui.formatting import truncate_string
from ..ui.theme import Emoji
from .base import MusicCog

logger = logging.getLogger(__name__)


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
        user_voice = getattr(interaction.user, "voice", None)
        if not user_voice or not user_voice.channel:
            await self.warn(interaction, "먼저 음성 채널에 접속해주세요.")
            return
        channel = user_voice.channel

        # 2) 봇이 이미 다른 채널에서 재생 중이면 거절
        player = self.registry.get(interaction.guild.id)
        if player and player.is_connected() and channel != player.voice_channel:
            await self.warn(interaction, "봇이 다른 음성 채널에서 재생 중입니다. 같은 채널에서 사용해주세요.")
            return

        await interaction.response.defer(thinking=True)

        # 3) 플레이어 확보 (연결)
        if player is None or not player.is_connected():
            try:
                if player:
                    await player.destroy(notify=False)
                voice_client = await channel.connect()
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] 음성 연결 실패 - %s", interaction.guild.name, exc, exc_info=True)
                await self.respond(interaction, self.embeds.error(f"음성 채널 연결 실패: {exc}"))
                return
            player = self.registry.create(
                guild=interaction.guild, text_channel=interaction.channel,
                voice_client=voice_client,
            )
        player.set_text_channel(interaction.channel)

        # 4) 해석
        try:
            result = await self.resolver.resolve(query, interaction.user.mention)
        except yt_dlp.utils.DownloadError as exc:
            await self.respond(interaction, self.embeds.error(self._download_error_message(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] 정보 검색 실패 - %s", interaction.guild.name, exc, exc_info=True)
            await self.respond(interaction, self.embeds.error(f"음악 정보를 가져오는 중 오류 발생: {exc}"))
            return

        if result is None:
            await self.respond(interaction, self.embeds.error("검색 결과가 없거나 처리 중 오류가 발생했습니다."))
            return

        # 5) 대기열 추가
        if isinstance(result, PlaylistResolution):
            player.set_playlist(result.original_url, result.next_start_index, interaction.user.mention)
            count = player.add_tracks(result.tracks)
            if count == 0:
                await self.respond(
                    interaction,
                    self.embeds.warning(f"플레이리스트 '{result.title}'에서 유효한 곡을 찾지 못했습니다."),
                )
                return
            await self.respond(
                interaction,
                self.embeds.playlist_added(result.title, count=count, requester=interaction.user.mention),
            )
        else:
            player.add_track(result.track)
            await self.respond(
                interaction,
                self.embeds.track_added(result.track, queue_position=player.queue_size),
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
        player = await self.require_control(interaction)
        if not player:
            return
        skipped = player.skip()
        if skipped is None:
            await self.warn(interaction, "재생 중인 곡이 없습니다.")
            return
        await self.respond(
            interaction,
            self.embeds.success(f"**{truncate_string(skipped.title, 40)}** 건너뛰었습니다."),
        )

    @app_commands.command(name="정지", description="음악 재생을 중지하고 봇을 퇴장시킵니다.")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        await player.destroy(notify=False)
        await self.respond(
            interaction,
            self.embeds.message(f"{Emoji.STOP} 음악 재생을 중지하고 연결을 종료했습니다."),
        )

    @app_commands.command(name="일시정지", description="음악 재생을 일시정지합니다.")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        if await player.pause():
            await self.respond(interaction, self.embeds.message(f"{Emoji.PAUSE} 일시정지되었습니다."))
        else:
            await self.warn(interaction, "재생 중인 곡이 없습니다.")

    @app_commands.command(name="재개", description="일시정지된 음악을 다시 재생합니다.")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = await self.require_control(interaction)
        if not player:
            return
        if await player.resume():
            await self.respond(interaction, self.embeds.success("재생을 재개합니다."))
        else:
            await self.warn(interaction, "일시정지된 곡이 없습니다.")

    @app_commands.command(name="현재곡", description="현재 재생 중인 곡 정보를 표시합니다.")
    @app_commands.guild_only()
    async def now_playing(self, interaction: discord.Interaction) -> None:
        player = await self.require_player(interaction)
        if not player:
            return
        if not player.current:
            await self.warn(interaction, "현재 재생 중인 곡이 없습니다.")
            return
        await interaction.response.defer()
        embed = self.embeds.progress(
            player.current, volume=player.volume, repeat_mode=player.repeat_mode,
            queue_size=player.queue_size, position=player.playback_position(),
        )
        await self.respond(interaction, embed)
