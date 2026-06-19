"""도메인 값 객체: 곡 메타데이터와 반복 모드."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RepeatMode(Enum):
    """반복 재생 모드. 순환 순서: OFF → ALL → ONE → OFF."""

    OFF = 0
    ALL = 1
    ONE = 2

    def next(self) -> "RepeatMode":
        order = (RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE)
        return order[(order.index(self) + 1) % len(order)]


@dataclass(frozen=True)
class Track:
    """재생할 곡의 불변 메타데이터.

    큐·히스토리·반복이 모두 이 값 객체를 재사용한다. 실제 오디오 소스는
    재생 직전 AudioSourceFactory가 stream_url로 생성한다.
    """

    title: str
    stream_url: str
    webpage_url: str
    duration: Optional[float]
    thumbnail: Optional[str]
    uploader: str
    requester: str
