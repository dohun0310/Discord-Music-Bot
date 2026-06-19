"""Track → 재생 가능한 discord 오디오 소스 변환 (지연 ffmpeg 생성)."""

from __future__ import annotations

from typing import Any, Protocol

import discord

from ..domain.models import Track


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
