"""합성 루트: 모든 의존성을 조립하고 봇을 구성한다."""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from .activity_log import command_context, format_command_args, register_command_logging
from .config import Settings
from .cogs.playback import PlaybackCog
from .cogs.queue import QueueCog
from .cogs.settings import SettingsCog
from .domain.models import Track
from .player.registry import PlayerRegistry
from .services.audio import DEFAULT_FFMPEG_OPTIONS, FFmpegSourceFactory
from .services.resolver import DEFAULT_YTDL_OPTIONS, YtDlpTrackResolver
from .ui.embeds import EmbedFactory
from .ui.formatting import truncate_string

logger = logging.getLogger(__name__)

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

    async def set_presence(track: Optional[Track]) -> None:
        """전역 presence 갱신 (여러 서버 동시 재생 시 마지막 곡 표시 - 현행 유지)."""
        if track is None:
            await bot.change_presence(activity=None)
            return
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=truncate_string(track.title, 40),
        )
        await bot.change_presence(activity=activity)

    embeds = EmbedFactory()
    resolver = YtDlpTrackResolver(
        ytdl_options=DEFAULT_YTDL_OPTIONS, batch_size=settings.playlist_batch_size,
        executor=executor,
    )
    source_factory = FFmpegSourceFactory(DEFAULT_FFMPEG_OPTIONS)
    registry = PlayerRegistry(
        settings=settings, resolver=resolver, source_factory=source_factory,
        embeds=embeds, set_presence=set_presence,
    )

    async def setup_hook() -> None:
        await bot.add_cog(PlaybackCog(bot, registry, embeds, settings, resolver))
        await bot.add_cog(QueueCog(bot, registry, embeds, settings))
        await bot.add_cog(SettingsCog(bot, registry, embeds, settings))
        # 재연결(on_ready 반복)마다 sync하지 않도록 여기서 1회만 실행한다.
        try:
            synced = await bot.tree.sync()
            logger.info("동기화된 명령어: %d개", len(synced))
        except Exception as exc:  # noqa: BLE001 - sync 실패가 기동을 막으면 안 됨
            logger.error("명령어 동기화 실패 - %s", exc)

    bot.setup_hook = setup_hook

    _register_events(bot, registry, embeds)
    return bot


def _register_events(bot: commands.Bot, registry: PlayerRegistry, embeds: EmbedFactory) -> None:
    # 모든 슬래시 명령 호출을 한국어로 중앙 집중 로깅 (SRP/DRY)
    register_command_logging(bot)

    @bot.event
    async def on_ready() -> None:
        print(
            f"\n  🎵 Discord Music Bot\n"
            f"  봇 이름: {bot.user.name}\n  봇 ID: {bot.user.id}\n"
            f"  Discord.py: {discord.__version__}\n"
            f"  시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        logger.info("봇 준비 완료 - %s (%s)", bot.user.name, bot.user.id)

    @bot.event
    async def on_voice_state_update(member, before, after) -> None:
        if bot.user is None:
            return
        await registry.notify_voice_state(member, before, after, bot.user.id)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error) -> None:
        guild_name, cmd, user = command_context(interaction)
        logger.error(
            "[%s] /%s 오류 - 사용자: %s%s - %s",
            guild_name, cmd, user, format_command_args(interaction), error, exc_info=True,
        )

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
