"""봇 설정: 환경 변수 기반 Settings + 색상/이모지/외부 도구 옵션."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import discord


@dataclass(frozen=True)
class Settings:
    """런타임 튜너블 설정. 합성 루트에서 한 번 생성해 주입한다."""

    bot_token: Optional[str]
    log_level: str
    idle_timeout: int = 60          # 음성 채널에 혼자일 때 대기(초)
    queue_timeout: int = 300        # 대기열이 빈 채 대기(초)
    max_queue_display: int = 10
    lazy_load_threshold: int = 3    # 플레이리스트 자동 로딩 임계값
    playlist_batch_size: int = 10
    default_volume: float = 0.5
    max_volume: float = 2.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=os.getenv("BOT_TOKEN"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


class Colors:
    """Discord 임베드 색상 테마."""

    PRIMARY = discord.Color.from_rgb(88, 101, 242)
    SUCCESS = discord.Color.from_rgb(87, 242, 135)
    WARNING = discord.Color.from_rgb(254, 231, 92)
    ERROR = discord.Color.from_rgb(237, 66, 69)
    INFO = discord.Color.from_rgb(88, 101, 242)
    MUSIC = discord.Color.from_rgb(255, 0, 127)
    QUEUE = discord.Color.from_rgb(138, 43, 226)


class Emoji:
    """봇에서 사용하는 이모지 (미사용 항목 제거)."""

    PLAY = "▶️"
    PAUSE = "⏸️"
    STOP = "⏹️"
    REPEAT = "🔁"
    REPEAT_ONE = "🔂"
    SHUFFLE = "🔀"
    VOLUME_HIGH = "🔊"
    VOLUME_LOW = "🔉"
    VOLUME_MUTE = "🔇"
    MUSIC = "🎵"
    PLAYLIST = "📋"
    QUEUE = "🎶"
    TIME = "⏱️"
    USER = "👤"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    DISCONNECT = "👋"
    EMPTY = "📭"


YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "outtmpl": "downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "extractor_args": {"youtube": {"player_client": ["android_vr"]}},
}

FFMPEG_OPTIONS = {
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 64k",
}
