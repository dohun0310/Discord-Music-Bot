"""Discord 임베드 색상·이모지 테마 (표현 계층 상수)."""

from __future__ import annotations

import discord


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
    """봇에서 사용하는 이모지."""

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
