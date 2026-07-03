"""봇 설정: 환경 변수 기반 Settings (합성 루트에서 1회 생성해 주입)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """런타임 튜너블 설정."""

    bot_token: Optional[str]
    log_level: str
    idle_timeout: int = 60           # 음성 채널에 혼자일 때 대기(초)
    queue_timeout: int = 300         # 대기열이 빈 채 대기(초)
    max_queue_display: int = 10
    lazy_load_threshold: int = 3     # 플레이리스트 자동 로딩 임계값
    playlist_batch_size: int = 10
    default_volume: float = 0.5
    max_volume: float = 2.0
    opus_bitrate: int = 128          # Opus 인코더 비트레이트(kbps)
    opus_signal_type: str = "music"  # 음악 최적화 Opus 시그널 타입 (auto/voice/music)
    stream_url_ttl: int = 14400      # 스트림 URL 신선도(초). 초과 시 재생 전 재해석
    max_consecutive_failures: int = 5  # 연속 재생 실패 시 중단 임계값

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=os.getenv("BOT_TOKEN"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
