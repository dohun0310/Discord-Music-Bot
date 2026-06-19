"""길드 1개의 음악 재생을 오케스트레이션한다.

도메인(TrackQueue, decide_next_track)·서비스(resolver, source_factory)·UI(embeds)
추상화에만 의존한다. ffmpeg는 재생 직전 생성하고, 큐에는 Track 값 객체만 보관한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import discord
from discord.ext import commands

from ..config import Settings
from ..domain.models import RepeatMode, Track
from ..domain.playback import decide_next_track
from ..domain.queue import TrackQueue
from ..services.audio import AudioSourceFactory
from ..services.resolver import TrackResolver
from ..ui.embeds import EmbedFactory

logger = logging.getLogger("discord.bot.player")


class GuildPlayer:
    def __init__(
        self, *, guild: discord.Guild, text_channel: discord.abc.Messageable,
        voice_client: discord.VoiceClient, bot: commands.Bot, settings: Settings,
        resolver: TrackResolver, source_factory: AudioSourceFactory,
        embeds: EmbedFactory, on_destroy: Callable[[int], None],
    ) -> None:
        self.guild = guild
        self.text_channel = text_channel
        self._voice_client: Optional[discord.VoiceClient] = voice_client
        self._bot = bot
        self._settings = settings
        self._resolver = resolver
        self._source_factory = source_factory
        self._embeds = embeds
        self._on_destroy = on_destroy

        self._queue = TrackQueue()
        self._history: list[Track] = []
        self._current: Optional[Track] = None
        self._start_time: Optional[float] = None
        self._volume = settings.default_volume
        self._repeat = RepeatMode.OFF
        self._paused = False

        self._playlist_url: Optional[str] = None
        self._next_playlist_index = 1
        self._loading_batch = False
        self._playlist_requester: Optional[str] = None

        self._new_track = asyncio.Event()
        self._next = asyncio.Event()
        self._destroyed = False
        self._background: set[asyncio.Task] = set()
        self._task = bot.loop.create_task(self._run())

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

    def snapshot(self) -> list[Track]:
        return self._queue.snapshot()

    def is_connected(self) -> bool:
        return bool(self._voice_client and self._voice_client.is_connected())

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
        self._playlist_url = url
        self._next_playlist_index = next_index
        self._playlist_requester = requester

    async def pause(self) -> bool:
        if self._voice_client and self._voice_client.is_playing():
            self._voice_client.pause()
            self._paused = True
            return True
        return False

    async def resume(self) -> bool:
        if self._voice_client and self._voice_client.is_paused():
            self._voice_client.resume()
            self._paused = False
            return True
        return False

    def set_volume(self, volume: float) -> float:
        self._volume = max(0.0, min(volume, self._settings.max_volume))
        if self._voice_client and isinstance(
            self._voice_client.source, discord.PCMVolumeTransformer
        ):
            self._voice_client.source.volume = self._volume
        return self._volume

    def toggle_repeat(self) -> RepeatMode:
        self._repeat = self._repeat.next()
        return self._repeat

    def shuffle_queue(self) -> int:
        return self._queue.shuffle()

    def clear_queue(self) -> int:
        count = self._queue.clear()
        self._history.clear()
        self._playlist_url = None
        self._next_playlist_index = 1
        self._loading_batch = False
        return count

    def remove(self, position: int) -> Track:
        return self._queue.remove(position)

    def skip(self) -> Optional[Track]:
        """현재 곡을 중지하고 다음으로 진행. 스킵된 곡을 반환(없으면 None)."""
        if not self._voice_client:
            return None
        if not (self._voice_client.is_playing() or self._voice_client.is_paused()):
            return None
        skipped = self._current
        if self._repeat == RepeatMode.ONE:
            self._repeat = RepeatMode.OFF
        self._voice_client.stop()
        return skipped

    def playback_position(self) -> Optional[float]:
        if not self._current or self._start_time is None:
            return None
        elapsed = self._bot.loop.time() - self._start_time
        if self._current.duration is not None:
            return min(elapsed, self._current.duration)
        return elapsed

    # ---------- 내부 헬퍼 ----------
    def _spawn(self, coro) -> None:
        task = self._bot.loop.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _channel_empty(self) -> bool:
        if not self._voice_client:
            return True
        return not [m for m in self._voice_client.channel.members if not m.bot]

    def _maybe_load_next_batch(self) -> None:
        if (
            self._playlist_url
            and not self._loading_batch
            and self._queue.size() < self._settings.lazy_load_threshold
        ):
            self._spawn(self._load_next_batch())

    async def _load_next_batch(self) -> None:
        if not self._playlist_url or self._loading_batch:
            return
        self._loading_batch = True
        url = self._playlist_url
        try:
            tracks = await self._resolver.load_playlist_batch(
                url, self._next_playlist_index, self._playlist_requester or "자동 로드"
            )
            if not tracks:
                self._playlist_url = None
                return
            added = self.add_tracks(tracks)
            self._next_playlist_index += added
            logger.info("[%s] 플레이리스트 배치 로드 %d곡", self.guild.name, added)
        except Exception as exc:  # noqa: BLE001 - 로깅 후 로딩 중단
            logger.error("[%s] 배치 로드 실패 - %s", self.guild.name, exc, exc_info=True)
            self._playlist_url = None
        finally:
            self._loading_batch = False

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

    async def _run(self) -> None:
        await self._bot.wait_until_ready()
        logger.info("[%s] 재생 루프 시작", self.guild.name)
        while not self._destroyed:
            self._next.clear()
            self._maybe_load_next_batch()

            if not self.is_connected():
                await self.destroy(notify=False)
                return

            if self._channel_empty():
                await self._handle_empty_channel()
                if not self.is_connected():
                    return
                continue

            track = decide_next_track(self._repeat, self._current, self._queue, self._history)
            if track is None:
                if await self._wait_for_track():
                    continue
                await self._notify_idle_disconnect()
                await self.destroy(notify=False)
                return

            await self._play(track)
            await self._next.wait()
            while self._voice_client and (
                self._voice_client.is_playing() or self._voice_client.is_paused()
            ):
                await asyncio.sleep(0.2)

    async def _play(self, track: Track) -> None:
        self._current = track
        self._paused = False
        try:
            source = self._source_factory.create(track, self._volume)
            self._voice_client.play(
                source,
                after=lambda e: self._bot.loop.call_soon_threadsafe(self._on_finished, e),
                bitrate=self._settings.opus_bitrate,
                signal_type=self._settings.opus_signal_type,
            )
            self._start_time = self._bot.loop.time()
            await self._update_presence()
            await self.text_channel.send(
                embed=self._embeds.now_playing(
                    track, volume=self._volume, repeat_mode=self._repeat,
                    queue_size=self._queue.size(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 재생 실패 시 다음 곡으로 진행
            logger.error("[%s] 재생 실패 - %s", self.guild.name, exc, exc_info=True)
            await self.text_channel.send(embed=self._embeds.error(f"재생 오류: {exc}"))
            self._current = None
            self._paused = False
            self._next.set()

    def _on_finished(self, error: Optional[Exception]) -> None:
        """ffmpeg after 콜백 (call_soon_threadsafe로 루프 스레드에서 실행)."""
        if error:
            logger.error("[%s] 재생 중 오류 - %s", self.guild.name, error)
            self._spawn(self.text_channel.send(embed=self._embeds.error(f"재생 중 오류: {error}")))
        if self._repeat != RepeatMode.ONE and self._voice_client and not self._voice_client.is_playing():
            self._current = None
        self._next.set()

    async def _update_presence(self) -> None:
        if not self._current:
            return
        from ..ui.formatting import truncate_string

        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=truncate_string(self._current.title, 40),
        )
        await self._bot.change_presence(activity=activity)

    async def _handle_empty_channel(self) -> None:
        await self.text_channel.send(
            embed=self._embeds.warning(
                f"음성 채널에 아무도 없습니다. {self._settings.idle_timeout}초 후 연결을 종료합니다."
            )
        )
        await asyncio.sleep(self._settings.idle_timeout)
        if not self.is_connected():
            return
        if self._channel_empty():
            await self.destroy(notify=True)

    async def _notify_idle_disconnect(self) -> None:
        minutes = self._settings.queue_timeout // 60
        try:
            await self.text_channel.send(
                embed=self._embeds.warning(
                    f"대기열이 {minutes}분 동안 비어있어 연결을 종료합니다."
                )
            )
        except Exception:  # noqa: BLE001
            pass

    async def destroy(self, notify: bool = True) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        guild_name = self.guild.name
        logger.info("[%s] 플레이어 정리 시작", guild_name)

        if self._voice_client and self._voice_client.is_playing():
            self._voice_client.stop()
        self.clear_queue()
        self._current = None
        self._paused = False

        try:
            await self._bot.change_presence(activity=None)
        except Exception:  # noqa: BLE001
            pass

        # 루프 밖에서 호출된 경우에만 태스크를 취소·대기 (자기 자신 await 방지)
        if self._task and not self._task.done() and asyncio.current_task() is not self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] 루프 종료 중 오류 - %s", guild_name, exc)

        if self._voice_client and self._voice_client.is_connected():
            await self._voice_client.disconnect(force=True)
        self._voice_client = None

        self._on_destroy(self.guild.id)

        if notify:
            try:
                await self.text_channel.send(
                    embed=self._embeds.info("음악 재생을 종료하고 음성 채널을 나갑니다.")
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] 종료 알림 실패 - %s", guild_name, exc)
        logger.info("[%s] 플레이어 정리 완료", guild_name)
