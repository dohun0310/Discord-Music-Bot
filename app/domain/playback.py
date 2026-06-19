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
