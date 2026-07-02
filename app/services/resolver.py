"""query → Track 해석. 순수 파싱 함수 + yt-dlp 비동기 어댑터.

순수 함수(build_resolution/build_batch/_entry_to_track/_best_thumbnail)는 단위
테스트가 쉽고, YtDlpTrackResolver는 yt-dlp 호출을 스레드 풀에서 수행한 뒤 위임한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Union

import yt_dlp

from ..domain.models import Track

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = ("url", "title", "webpage_url")


@dataclass(frozen=True)
class TrackResolution:
    """단일 곡 또는 검색 결과."""

    track: Track


@dataclass(frozen=True)
class PlaylistResolution:
    """플레이리스트 첫 배치 + lazy loading 메타데이터."""

    title: str
    original_url: str
    tracks: list[Track]
    next_start_index: int


ResolveResult = Union[TrackResolution, PlaylistResolution]


def _best_thumbnail(thumbnails: list[dict[str, Any]]) -> Optional[str]:
    candidates = [t for t in thumbnails if t.get("url")]
    if not candidates:
        return None
    candidates.sort(
        key=lambda x: (x.get("height", 0) or 0) * (x.get("width", 0) or 0), reverse=True
    )
    return candidates[0]["url"]


def _entry_to_track(
    entry: Optional[dict[str, Any]], requester: str,
    resolved_at: Optional[float] = None,
) -> Optional[Track]:
    if not entry:
        return None
    if not all(key in entry for key in _REQUIRED_KEYS):
        missing = [k for k in _REQUIRED_KEYS if k not in entry]
        logger.warning("항목 누락으로 제외 - 키: %s, 제목: %s", missing, entry.get("title"))
        return None
    thumbnail = entry.get("thumbnail")
    if not thumbnail and entry.get("thumbnails"):
        thumbnail = _best_thumbnail(entry["thumbnails"])
    return Track(
        title=entry["title"],
        stream_url=entry["url"],
        webpage_url=entry["webpage_url"],
        duration=entry.get("duration"),
        thumbnail=thumbnail,
        uploader=entry.get("uploader", "알 수 없음"),
        requester=requester,
        resolved_at=resolved_at,
    )


def build_resolution(
    data: dict[str, Any], *, query: str, requester: str, is_search: bool,
    resolved_at: Optional[float] = None,
) -> Optional[ResolveResult]:
    """extract_info 결과(dict)를 도메인 결과로 변환한다 (초기 해석용, 순수)."""
    if "entries" in data:
        valid = [
            t for t in (
                _entry_to_track(e, requester, resolved_at) for e in data["entries"]
            ) if t
        ]
        if not valid:
            return None
        if is_search:
            return TrackResolution(track=valid[0])
        title = data.get("title", "알 수 없는 플레이리스트")
        original_url = data.get("webpage_url") or data.get("original_url") or query
        return PlaylistResolution(
            title=title, original_url=original_url, tracks=valid,
            next_start_index=1 + len(valid),
        )
    track = _entry_to_track(data, requester, resolved_at)
    return TrackResolution(track=track) if track else None


def build_batch(
    data: dict[str, Any], requester: str, resolved_at: Optional[float] = None,
) -> list[Track]:
    """플레이리스트 다음 배치(dict)를 Track 리스트로 변환한다 (순수)."""
    if "entries" not in data:
        return []
    return [
        t for t in (
            _entry_to_track(e, requester, resolved_at) for e in data["entries"]
        ) if t
    ]


class TrackResolver(Protocol):
    async def resolve(self, query: str, requester: str) -> Optional[ResolveResult]: ...
    async def load_playlist_batch(
        self, url: str, start_index: int, requester: str
    ) -> list[Track]: ...
    async def refresh(self, track: Track) -> Optional[Track]: ...


class YtDlpTrackResolver:
    """yt-dlp 기반 TrackResolver 구현."""

    def __init__(
        self, *, ytdl_options: dict[str, Any], batch_size: int,
        executor: ThreadPoolExecutor, ytdl_factory=yt_dlp.YoutubeDL,
    ) -> None:
        self._options = ytdl_options
        self._batch_size = batch_size
        self._executor = executor
        self._ytdl_factory = ytdl_factory

    async def _extract(self, query: str, playlist_items: str) -> Optional[dict[str, Any]]:
        opts = dict(self._options)
        opts["playlist_items"] = playlist_items
        ytdl = self._ytdl_factory(opts)
        # 실행 중인 이벤트 루프를 호출 시점에 얻는다. (생성 시점의 bot.loop은
        # discord.py 2.x에서 아직 _LoopSentinel이라 저장해두면 런타임에 깨진다.)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, lambda: ytdl.extract_info(query, download=False)
        )

    async def resolve(self, query: str, requester: str) -> Optional[ResolveResult]:
        is_search = not query.startswith(("http://", "https://"))
        data = await self._extract(query, f"1-{self._batch_size}")
        if data is None:
            return None
        return build_resolution(
            data, query=query, requester=requester, is_search=is_search,
            resolved_at=time.monotonic(),
        )

    async def load_playlist_batch(
        self, url: str, start_index: int, requester: str
    ) -> list[Track]:
        end = start_index + self._batch_size - 1
        data = await self._extract(url, f"{start_index}-{end}")
        if data is None:
            return []
        return build_batch(data, requester, resolved_at=time.monotonic())

    async def refresh(self, track: Track) -> Optional[Track]:
        """만료 의심 트랙을 webpage_url로 재해석해 새 Track을 반환한다."""
        data = await self._extract(track.webpage_url, "1")
        if data is None:
            return None
        entry: Optional[dict[str, Any]] = data
        if "entries" in data:
            entries = [e for e in data["entries"] if e]
            entry = entries[0] if entries else None
        return _entry_to_track(entry, track.requester, resolved_at=time.monotonic())
