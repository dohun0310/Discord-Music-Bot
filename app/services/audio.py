"""Track → 재생 가능한 discord 오디오 소스 변환 (지연 ffmpeg 생성)."""

from __future__ import annotations

from typing import Any, Protocol

import discord

from ..domain.models import Track

DEFAULT_FFMPEG_OPTIONS: dict[str, Any] = {
    # 네트워크 스트림이 중간에 끊겨도 자동 재연결 (간헐적 끊김/끊김음 완화)
    "before_options": (
        "-nostdin "
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_on_network_error 1 -reconnect_on_http_error 4xx,5xx"
    ),
    # 비디오 스트림 제거
    "options": "-vn",
}


class AudioSourceFactory(Protocol):
    def create(self, track: Track, volume: float) -> discord.AudioSource: ...


class FFmpegSourceFactory:
    """재생 직전 호출되어 ffmpeg 서브프로세스를 1개만 생성한다.

    소스/트랜스포머 클래스를 주입받아 단위 테스트에서 실제 ffmpeg 없이 검증 가능.
    """

    def __init__(
        self, ffmpeg_options: dict[str, Any], *,
        source_cls=discord.FFmpegPCMAudio,
        transformer_cls=discord.PCMVolumeTransformer,
    ) -> None:
        self._ffmpeg_options = ffmpeg_options
        self._source_cls = source_cls
        self._transformer_cls = transformer_cls

    def create(self, track: Track, volume: float) -> discord.AudioSource:
        base = self._source_cls(track.stream_url, **self._ffmpeg_options)
        return self._transformer_cls(base, volume=volume)
