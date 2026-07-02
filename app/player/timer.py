"""일시정지를 반영한 재생 위치 추적 (순수, 시간 주입).

시간 값은 호출자가 단조 시계(loop.time 등)로 주입한다. asyncio/discord 의존이
없어 단위 테스트가 쉽다.
"""

from __future__ import annotations

from typing import Optional


class PlaybackTimer:
    def __init__(self) -> None:
        self._started_at: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._paused_total = 0.0

    def start(self, now: float) -> None:
        """재생 시작(재시작 포함). 일시정지 누적을 초기화한다."""
        self._started_at = now
        self._paused_at = None
        self._paused_total = 0.0

    def pause(self, now: float) -> None:
        if self._started_at is not None and self._paused_at is None:
            self._paused_at = now

    def resume(self, now: float) -> None:
        if self._paused_at is not None:
            self._paused_total += now - self._paused_at
            self._paused_at = None

    def stop(self) -> None:
        self._started_at = None
        self._paused_at = None
        self._paused_total = 0.0

    def position(self, now: float) -> Optional[float]:
        """실제 재생 위치(초). 시작 전이면 None."""
        if self._started_at is None:
            return None
        end = self._paused_at if self._paused_at is not None else now
        return end - self._started_at - self._paused_total
