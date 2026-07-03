"""플레이리스트 지연 로딩 상태와 배치 로드 (GuildPlayer에서 분리).

로딩 플래그는 maybe_load에서 동기적으로 세워 이중 로드 레이스를 막는다.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, List, Optional

from ..domain.models import Track
from ..services.resolver import TrackResolver

logger = logging.getLogger(__name__)

AddTracks = Callable[[List[Track]], int]
Spawn = Callable[[Coroutine[Any, Any, None]], None]


class PlaylistAutoLoader:
    def __init__(
        self, *, resolver: TrackResolver, threshold: int, guild_name: str = "",
    ) -> None:
        self._resolver = resolver
        self._threshold = threshold
        self._guild_name = guild_name
        self._url: Optional[str] = None
        self._next_index = 1
        self._requester: Optional[str] = None
        self._loading = False

    @property
    def active(self) -> bool:
        return self._url is not None

    def set(self, url: str, next_index: int, requester: str) -> None:
        self._url = url
        self._next_index = next_index
        self._requester = requester

    def clear(self) -> None:
        self._url = None
        self._next_index = 1
        self._requester = None

    def maybe_load(self, queue_size: int, add_tracks: AddTracks, spawn: Spawn) -> None:
        """대기열이 임계값 미만이면 다음 배치 로드를 spawn한다 (비차단)."""
        if self.active and not self._loading and queue_size < self._threshold:
            self._loading = True
            spawn(self._load(add_tracks))

    async def _load(self, add_tracks: AddTracks) -> None:
        url = self._url
        try:
            if url is None:
                return
            tracks = await self._resolver.load_playlist_batch(
                url, self._next_index, self._requester or "자동 로드"
            )
            if not tracks:
                self.clear()  # 플레이리스트 끝
                return
            added = add_tracks(tracks)
            self._next_index += added
            logger.info("[%s] 플레이리스트 배치 로드 %d곡", self._guild_name, added)
        except Exception as exc:  # noqa: BLE001 - 로딩 실패 시 자동 로드 포기
            logger.error("[%s] 배치 로드 실패 - %s", self._guild_name, exc, exc_info=True)
            self.clear()
        finally:
            self._loading = False
