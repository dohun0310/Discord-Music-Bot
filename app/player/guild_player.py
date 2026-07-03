"""길드 1개의 음악 재생 오케스트레이션.

큐(도메인)·타이머·자동로더·알림 협력 객체를 조율하고 재생 루프를 돌린다.
discord Bot 전체가 아니라 presence 콜백과 리졸버·소스 팩토리 추상화에만
의존한다(ISP/DIP). 루프 최상위 예외 가드로 좀비 플레이어를 방지한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Coroutine, Optional

import discord

from ..config import Settings
from ..domain.models import RepeatMode, Track
from ..domain.playback import decide_next_track, is_playback_failure
from ..domain.queue import TrackQueue
from ..services.audio import AudioSourceFactory
from ..services.resolver import TrackResolver
from ..ui.embeds import EmbedFactory
from .autoloader import PlaylistAutoLoader
from .notifier import ChannelNotifier
from .timer import PlaybackTimer

logger = logging.getLogger(__name__)

SetPresence = Callable[[Optional[Track]], Awaitable[None]]


class GuildPlayer:
    def __init__(
        self, *, guild: discord.Guild, text_channel: discord.abc.Messageable,
        voice_client: discord.VoiceClient, settings: Settings,
        resolver: TrackResolver, source_factory: AudioSourceFactory,
        embeds: EmbedFactory, set_presence: SetPresence,
        on_destroy: Callable[[int], None],
    ) -> None:
        self.guild = guild
        self._voice_client: Optional[discord.VoiceClient] = voice_client
        self._settings = settings
        self._resolver = resolver
        self._source_factory = source_factory
        self._embeds = embeds
        self._set_presence = set_presence
        self._on_destroy = on_destroy

        self._loop = asyncio.get_running_loop()
        self._notifier = ChannelNotifier(text_channel, guild_name=guild.name)
        self._timer = PlaybackTimer()
        self._autoloader = PlaylistAutoLoader(
            resolver=resolver, threshold=settings.lazy_load_threshold,
            guild_name=guild.name,
        )

        self._queue = TrackQueue()
        self._history: list[Track] = []
        self._current: Optional[Track] = None
        self._volume = settings.default_volume
        self._repeat = RepeatMode.OFF
        self._paused = False
        self._skip_requested = False
        self._consecutive_failures = 0

        self._new_track = asyncio.Event()
        self._next = asyncio.Event()
        self._destroyed = False
        self._background: set[asyncio.Task] = set()
        self._empty_task: Optional[asyncio.Task] = None
        self._task = self._loop.create_task(self._run())

        logger.info("[%s] GuildPlayer 생성", guild.name)

    # ---------- 속성 ----------
    @property
    def current(self) -> Optional[Track]:
        return self._current

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def repeat_mode(self) -> RepeatMode:
        return self._repeat

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def queue_size(self) -> int:
        return self._queue.size()

    @property
    def voice_channel(self):
        """연결 중인 음성 채널 (미연결이면 None). 같은 채널 검증에 사용."""
        if self._voice_client and self._voice_client.is_connected():
            return self._voice_client.channel
        return None

    def snapshot(self) -> list[Track]:
        return self._queue.snapshot()

    def is_connected(self) -> bool:
        return bool(self._voice_client and self._voice_client.is_connected())

    def set_text_channel(self, channel: discord.abc.Messageable) -> None:
        self._notifier.set_channel(channel)

    # ---------- 큐/재생 명령 ----------
    def add_track(self, track: Track) -> None:
        self._queue.add(track)
        self._new_track.set()

    def add_tracks(self, tracks: list[Track]) -> int:
        for track in tracks:
            self._queue.add(track)
        if tracks:
            self._new_track.set()
        return len(tracks)

    def set_playlist(self, url: str, next_index: int, requester: str) -> None:
        self._autoloader.set(url, next_index, requester)
        self._new_track.set()  # 루프를 깨워 첫 배치 로드를 시작

    async def pause(self) -> bool:
        if self._voice_client and self._voice_client.is_playing():
            self._voice_client.pause()
            self._paused = True
            self._timer.pause(self._loop.time())
            logger.info("[%s] 재생 일시정지", self.guild.name)
            return True
        return False

    async def resume(self) -> bool:
        if self._voice_client and self._voice_client.is_paused():
            self._voice_client.resume()
            self._paused = False
            self._timer.resume(self._loop.time())
            logger.info("[%s] 재생 재개", self.guild.name)
            return True
        return False

    def set_volume(self, volume: float) -> float:
        self._volume = max(0.0, min(volume, self._settings.max_volume))
        if self._voice_client and isinstance(
            self._voice_client.source, discord.PCMVolumeTransformer
        ):
            self._voice_client.source.volume = self._volume
        logger.info("[%s] 볼륨 설정: %.0f%%", self.guild.name, self._volume * 100)
        return self._volume

    def toggle_repeat(self) -> RepeatMode:
        self._repeat = self._repeat.next()
        logger.info("[%s] 반복 모드 변경: %s", self.guild.name, self._repeat.name)
        return self._repeat

    def shuffle_queue(self) -> int:
        count = self._queue.shuffle()
        if count:
            logger.info("[%s] 대기열 셔플: %d곡", self.guild.name, count)
        return count

    def clear_queue(self) -> int:
        count = self._queue.clear()
        self._history.clear()
        self._autoloader.clear()
        if count:
            logger.info("[%s] 대기열 비움 - 제거: %d곡", self.guild.name, count)
        return count

    def remove(self, position: int) -> Track:
        track = self._queue.remove(position)
        logger.info("[%s] 대기열에서 곡 제거: '%s'", self.guild.name, track.title)
        return track

    def skip(self) -> Optional[Track]:
        """현재 곡을 중지하고 다음으로 진행. 반복 모드는 유지한다."""
        if not self._voice_client:
            return None
        if not (self._voice_client.is_playing() or self._voice_client.is_paused()):
            return None
        skipped = self._current
        self._current = None        # 한곡 반복이어도 다음 곡을 집도록
        self._skip_requested = True  # 빠른 종료를 실패로 오인하지 않도록
        self._voice_client.stop()
        logger.info("[%s] 건너뛰기: '%s'", self.guild.name, getattr(skipped, "title", "알 수 없음"))
        return skipped

    def playback_position(self) -> Optional[float]:
        if self._current is None:
            return None
        pos = self._timer.position(self._loop.time())
        if pos is None:
            return None
        if self._current.duration is not None:
            return min(pos, self._current.duration)
        return pos

    # ---------- 내부 헬퍼 ----------
    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = self._loop.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _channel_empty(self) -> bool:
        if not self._voice_client:
            return True
        return not [m for m in self._voice_client.channel.members if not m.bot]

    # ---------- 빈 채널 감시 (이벤트 기반) ----------
    def on_voice_members_changed(self) -> None:
        """음성 상태 이벤트 수신 시 registry가 호출한다."""
        self._recheck_empty()

    def _recheck_empty(self) -> None:
        if self._destroyed or not self.is_connected():
            return
        if self._channel_empty():
            if self._empty_task is None or self._empty_task.done():
                self._empty_task = self._loop.create_task(self._empty_grace())
        elif self._empty_task and not self._empty_task.done():
            self._empty_task.cancel()
            self._empty_task = None

    async def _empty_grace(self) -> None:
        """빈 채널 경고 후 유예 시간 내 복귀 없으면 종료한다."""
        await self._notifier.send(self._embeds.warning(
            f"음성 채널에 아무도 없습니다. {self._settings.idle_timeout}초 후 연결을 종료합니다."
        ))
        await asyncio.sleep(self._settings.idle_timeout)
        if self.is_connected() and self._channel_empty():
            logger.info("[%s] 빈 채널 유예 만료 - 종료", self.guild.name)
            await self.destroy(notify=True)

    # ---------- 재생 루프 ----------
    async def _run(self) -> None:
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 좀비 플레이어 방지: 어떤 예외도 정리로 수렴
            logger.exception("[%s] 재생 루프 비정상 종료", self.guild.name)
            await self._notifier.send(
                self._embeds.error("재생 루프 오류가 발생해 재생을 종료합니다.")
            )
            await self.destroy(notify=False)

    async def _run_loop(self) -> None:
        logger.info("[%s] 재생 루프 시작", self.guild.name)
        while not self._destroyed:
            self._next.clear()
            self._autoloader.maybe_load(self._queue.size(), self.add_tracks, self._spawn)

            if not self.is_connected():
                await self.destroy(notify=False)
                return
            self._recheck_empty()  # 이벤트 유실 대비 안전망 (비차단)

            track = decide_next_track(self._repeat, self._current, self._queue, self._history)
            if track is None:
                if await self._wait_for_track():
                    continue
                await self._notify_idle_disconnect()
                await self.destroy(notify=False)
                return

            await self._play(track)
            await self._next.wait()

            if self._consecutive_failures >= self._settings.max_consecutive_failures:
                await self._notifier.send(
                    self._embeds.error("재생이 연속으로 실패해 재생을 종료합니다.")
                )
                await self.destroy(notify=False)
                return
            if self._repeat != RepeatMode.ONE:
                self._current = None

    async def _wait_for_track(self) -> bool:
        """새 곡이 들어오거나 타임아웃될 때까지 대기. True=곡 있음, False=타임아웃."""
        self._new_track.clear()
        if not self._queue.is_empty():
            return True
        try:
            await asyncio.wait_for(
                self._new_track.wait(), timeout=self._settings.queue_timeout
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _ensure_fresh(self, track: Track) -> Track:
        """스트림 URL이 TTL을 넘겼으면 재해석한 새 Track을 반환한다."""
        if track.resolved_at is None:
            return track
        age = time.monotonic() - track.resolved_at
        if age <= self._settings.stream_url_ttl:
            return track
        logger.info("[%s] 스트림 URL 만료(%.0f초 경과) - 재해석: '%s'",
                    self.guild.name, age, track.title)
        refreshed = await self._resolver.refresh(track)
        if refreshed is None:
            raise RuntimeError(f"만료된 곡 재해석 실패: {track.title}")
        return refreshed

    async def _play(self, track: Track) -> None:
        self._current = track
        self._paused = False
        try:
            track = await self._ensure_fresh(track)
            self._current = track
            voice = self._voice_client
            if voice is None or not voice.is_connected():
                raise RuntimeError("음성 연결이 끊어졌습니다.")
            source = self._source_factory.create(track, self._volume)
            voice.play(
                source,
                after=lambda e: self._loop.call_soon_threadsafe(self._on_finished, e),
                bitrate=self._settings.opus_bitrate,
                signal_type=self._settings.opus_signal_type,
            )
            self._timer.start(self._loop.time())
            await self._update_presence(track)
            await self._notifier.send(
                self._embeds.now_playing(
                    track, volume=self._volume, repeat_mode=self._repeat,
                    queue_size=self._queue.size(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 재생 실패 시 다음 곡으로 진행
            logger.error("[%s] 재생 실패 - %s", self.guild.name, exc, exc_info=True)
            await self._notifier.send(self._embeds.error(f"재생 오류: {exc}"))
            self._current = None
            self._paused = False
            self._consecutive_failures += 1
            self._next.set()

    def _on_finished(self, error: Optional[Exception]) -> None:
        """voice 재생 종료 콜백 (call_soon_threadsafe로 루프 스레드에서 실행)."""
        if self._destroyed:
            return
        elapsed = self._timer.position(self._loop.time())
        self._timer.stop()
        duration = self._current.duration if self._current else None
        skipped, self._skip_requested = self._skip_requested, False
        if error:
            logger.error("[%s] 재생 중 오류 - %s", self.guild.name, error)
            self._spawn(self._notifier.send(self._embeds.error(f"재생 중 오류: {error}")))
        if skipped or not is_playback_failure(error is not None, elapsed, duration):
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._repeat == RepeatMode.ONE:
                self._current = None  # 실패한 곡 무한 반복 방지
        self._next.set()

    async def _update_presence(self, track: Optional[Track]) -> None:
        try:
            await self._set_presence(track)
        except Exception as exc:  # noqa: BLE001 - presence 실패는 재생에 영향 없음
            logger.warning("[%s] presence 갱신 실패 - %s", self.guild.name, exc)

    async def _notify_idle_disconnect(self) -> None:
        minutes = self._settings.queue_timeout // 60
        await self._notifier.send(self._embeds.warning(
            f"대기열이 {minutes}분 동안 비어있어 연결을 종료합니다."
        ))

    # ---------- 정리 ----------
    async def destroy(self, notify: bool = True) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        guild_name = self.guild.name
        logger.info("[%s] 플레이어 정리 시작", guild_name)

        current_task = asyncio.current_task()
        if self._empty_task and not self._empty_task.done() and current_task is not self._empty_task:
            self._empty_task.cancel()
        for task in list(self._background):
            task.cancel()

        if self._voice_client and (
            self._voice_client.is_playing() or self._voice_client.is_paused()
        ):
            self._voice_client.stop()
        self.clear_queue()
        self._current = None
        self._paused = False
        self._timer.stop()

        await self._update_presence(None)

        # 루프 밖에서 호출된 경우에만 태스크를 취소·대기 (자기 자신 await 방지)
        if self._task and not self._task.done() and current_task is not self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] 루프 종료 중 오류 - %s", guild_name, exc)

        if self._voice_client and self._voice_client.is_connected():
            try:
                await self._voice_client.disconnect(force=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] 음성 연결 해제 실패 - %s", guild_name, exc)
        self._voice_client = None

        self._on_destroy(self.guild.id)

        if notify:
            await self._notifier.send(
                self._embeds.info("음악 재생을 종료하고 음성 채널을 나갑니다.")
            )
        logger.info("[%s] 플레이어 정리 완료", guild_name)
