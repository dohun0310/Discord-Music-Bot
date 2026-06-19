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
    opus_bitrate: int = 128          # Opus 인코더 비트레이트(kbps)
    opus_signal_type: str = "music"  # 음악 최적화 Opus 시그널 타입 (auto/voice/music)

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
    # 네트워크 스트림이 중간에 끊겨도 자동 재연결 (간헐적 끊김/끊김음 완화)
    "before_options": (
        "-nostdin "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx"
    ),
    # 비디오 스트림 제거 (PCM 출력엔 무의미하던 -bufsize 제거)
    "options": "-vn",
}
