"""순수 동기 트랙 큐 자료구조.

asyncio 의존이 없어 단위 테스트가 쉽다. 재생 루프의 대기/타임아웃 같은
비동기 조율은 GuildPlayer가 담당한다(관심사 분리).
"""

from __future__ import annotations

import random
from collections import deque
from typing import Optional

from .models import Track


class TrackQueue:
    def __init__(self) -> None:
        self._items: deque[Track] = deque()

    def add(self, track: Track) -> None:
        self._items.append(track)

    def get(self) -> Optional[Track]:
        if not self._items:
            return None
        return self._items.popleft()

    def snapshot(self) -> list[Track]:
        return list(self._items)

    def size(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        return not self._items

    def clear(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def shuffle(self) -> int:
        if len(self._items) < 2:
            return 0
        items = list(self._items)
        random.shuffle(items)
        self._items = deque(items)
        return len(items)

    def remove(self, position: int) -> Track:
        """1부터 시작하는 순번의 곡을 제거하고 반환한다."""
        if position < 1 or position > len(self._items):
            raise IndexError(f"유효하지 않은 순번: {position}")
        items = list(self._items)
        removed = items.pop(position - 1)
        self._items = deque(items)
        return removed
