"""합성 루트: 모든 의존성을 조립하고 봇을 구성한다."""

from __future__ import annotations

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from .config import FFMPEG_OPTIONS, Settings, YTDL_OPTIONS
from .cogs.playback import PlaybackCog
from .cogs.queue import QueueCog
from .cogs.settings import SettingsCog
from .player.registry import PlayerRegistry
from .services.audio import FFmpegSourceFactory
from .services.resolver import YtDlpTrackResolver
from .ui.embeds import EmbedFactory

logger = logging.getLogger("discord.bot.main")

# yt-dlp 버그 리포트 메시지 비활성화
yt_dlp.utils.bug_reports_message = lambda *a, **k: ""


def build_bot(settings: Settings) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    # ----- 의존성 조립 (DIP: 구체 구현을 여기서만 생성) -----
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdl")
    atexit.register(executor.shutdown, wait=False)

    embeds = EmbedFactory()
    resolver = YtDlpTrackResolver(
        ytdl_options=YTDL_OPTIONS, batch_size=settings.playlist_batch_size,
        loop=bot.loop, executor=executor,
    )
    source_factory = FFmpegSourceFactory(FFMPEG_OPTIONS)
    registry = PlayerRegistry(
        bot=bot, settings=settings, resolver=resolver,
        source_factory=source_factory, embeds=embeds,
    )

    async def setup_hook() -> None:
        await bot.add_cog(PlaybackCog(bot, registry, embeds, settings, resolver))
        await bot.add_cog(QueueCog(bot, registry, embeds, settings))
        await bot.add_cog(SettingsCog(bot, registry, embeds, settings))

    bot.setup_hook = setup_hook

    _register_events(bot, registry, embeds)
    return bot


def _register_events(bot: commands.Bot, registry: PlayerRegistry, embeds: EmbedFactory) -> None:
    @bot.event
    async def on_ready() -> None:
        print(
            f"\n  🎵 Discord Music Bot\n"
            f"  봇 이름: {bot.user.name}\n  봇 ID: {bot.user.id}\n"
            f"  Discord.py: {discord.__version__}\n"
            f"  시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        logger.info("봇 준비 완료 - %s (%s)", bot.user.name, bot.user.id)
        try:
            synced = await bot.tree.sync()
            print(f"  ✓ 동기화된 명령어: {len(synced)}개")
        except Exception as exc:  # noqa: BLE001
            logger.error("명령어 동기화 실패 - %s", exc)

    @bot.event
    async def on_voice_state_update(member, before, after) -> None:
        if member.id == bot.user.id and before.channel and not after.channel:
            player = registry.get(member.guild.id)
            if player:
                logger.info("[%s] 봇 음성 연결 해제 감지 - 플레이어 정리", member.guild.name)
                await player.destroy(notify=False)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error) -> None:
        guild_name = interaction.guild.name if interaction.guild else "DM"
        cmd = interaction.command.name if interaction.command else "알 수 없음"
        logger.error("[%s] 명령어 오류 - %s: %s", guild_name, cmd, error, exc_info=True)

        if isinstance(error, app_commands.NoPrivateMessage):
            msg = "이 명령어는 DM에서 사용할 수 없습니다."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"명령어를 너무 자주 사용하고 있습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = f"봇에게 필요한 권한이 없습니다: {', '.join(error.missing_permissions)}"
        else:
            msg = "명령어 처리 중 오류가 발생했습니다."

        embed = embeds.error(msg)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.NotFound:
            logger.warning("[%s] 오류 메시지 전송 실패 - 상호작용 없음", guild_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("오류 메시지 전송 중 예외 - %s", exc)
