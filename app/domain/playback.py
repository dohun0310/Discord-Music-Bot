"""다음 재생 곡 결정 정책 (순수 함수).

GuildPlayer가 매 루프마다 호출한다. discord/asyncio 의존이 없어 테스트가 쉽다.
"""

from __future__ import annotations

from typing import Optional

from .models import RepeatMode, Track
from .queue import TrackQueue


def decide_next_track(
    repeat: RepeatMode,
    current: Optional[Track],
    queue: TrackQueue,
    history: list[Track],
) -> Optional[Track]:
    """반복 모드를 고려해 다음 곡을 결정한다. queue/history를 부수적으로 변경한다.

    - ONE: 현재 곡을 그대로 반환(큐 미소비).
    - ALL: 큐가 비고 히스토리가 있으면 히스토리를 큐로 복원한 뒤 진행.
           꺼낸 곡은 히스토리에 누적한다.
    - OFF: 큐에서 하나 꺼내 반환.
    반환 None이면 재생할 곡이 없음을 의미한다.
    """
    if repeat == RepeatMode.ONE and current is not None:
        return current

    if repeat == RepeatMode.ALL and queue.is_empty() and history:
        for track in history:
            queue.add(track)
        history.clear()

    track = queue.get()
    if track is not None and repeat == RepeatMode.ALL:
        history.append(track)
    return track


MIN_PLAY_SECONDS = 2.0     # 이보다 빨리 끝나면 비정상 종료 의심
SHORT_TRACK_CUTOFF = 10.0  # 이보다 짧은 곡은 빠른 종료가 정상일 수 있어 제외


def is_playback_failure(
    had_error: bool, elapsed: Optional[float], duration: Optional[float],
) -> bool:
    """재생 종료가 실패인지 판정한다 (연속 실패 중단 정책의 입력).

    (a) 에러를 수반한 종료, 또는 (b) 곡 길이가 SHORT_TRACK_CUTOFF 이상인데
    MIN_PLAY_SECONDS 미만 만에 끝난 경우(즉시 죽은 ffmpeg 추정)를 실패로 본다.
    """
    if had_error:
        return True
    return (
        elapsed is not None
        and elapsed < MIN_PLAY_SECONDS
        and duration is not None
        and duration >= SHORT_TRACK_CUTOFF
    )
