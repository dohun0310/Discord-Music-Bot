"""
음악 플레이어 모듈

각 서버(길드)별 음악 재생을 관리합니다.
대기열 관리, 재생 루프, 플레이리스트 lazy loading을 담당합니다.
"""

import asyncio
import logging
import random
from enum import Enum
from typing import Any, Optional

import discord
from discord.ext import commands

from config import (
    Colors,
    DEFAULT_VOLUME,
    Emoji,
    FFMPEG_OPTIONS,
    IDLE_TIMEOUT,
    LAZY_LOAD_THRESHOLD,
    MAX_VOLUME,
    QUEUE_TIMEOUT,
)
from utils import (
    create_ffmpeg_source,
    create_progress_bar,
    format_time,
    is_valid_entry,
    make_embed,
    make_error_embed,
    truncate_string,
)

logger = logging.getLogger('discord.bot.player')


class RepeatMode(Enum):
    """반복 재생 모드"""
    OFF = 0  # 반복 없음
    ONE = 1  # 한 곡 반복
    ALL = 2  # 전체 반복


class MusicPlayer:
    """
    음악 플레이어 클래스

    각 서버(길드)마다 하나의 인스턴스가 생성되어
    해당 서버의 음악 재생을 관리합니다.

    Attributes:
        guild: Discord 서버 객체
        text_channel: 메시지를 보낼 텍스트 채널
        voice_client: 음성 연결 클라이언트
        queue: 재생 대기열
        current: 현재 재생 중인 곡
        volume: 볼륨 (0.0 ~ 2.0)
        repeat_mode: 반복 재생 모드
        shuffle: 셔플 활성화 여부
    """

    def __init__(
        self,
        guild: discord.Guild,
        text_channel: discord.TextChannel,
        voice_client: discord.VoiceClient,
        bot: commands.Bot
    ):
        """
        MusicPlayer 인스턴스를 초기화합니다.

        Args:
            guild: Discord 서버 객체
            text_channel: 메시지를 보낼 텍스트 채널
            voice_client: 음성 연결 클라이언트
            bot: Discord 봇 인스턴스
        """
        self.guild = guild
        self.text_channel = text_channel
        self.voice_client: Optional[discord.VoiceClient] = voice_client
        self.bot = bot

        # 재생 관련 상태
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.history: list[Any] = []  # 재생 히스토리 (전체 반복용)
        self.next = asyncio.Event()
        self.current: Optional[Any] = None
        self.start_time: Optional[float] = None

        # 재생 설정
        self.volume: float = DEFAULT_VOLUME
        self.repeat_mode: RepeatMode = RepeatMode.OFF
        self.shuffle: bool = False
        self.paused: bool = False

        # 플레이리스트 lazy loading 상태
        self.current_playlist_url: Optional[str] = None
        self.next_playlist_index: int = 1
        self.loading_next_batch: bool = False
        self.playlist_requester: Optional[str] = None

        # 재생 루프 태스크 시작
        self.player_task = self.bot.loop.create_task(self.player_loop())

        logger.info(
            f"[{self.guild.name}] MusicPlayer 초기화 완료 - "
            f"텍스트 채널: #{text_channel.name}, "
            f"음성 채널: {voice_client.channel.name}"
        )

    def get_queue_items(self) -> list[Any]:
        """
        현재 대기열의 모든 항목을 리스트로 반환합니다.

        Returns:
            대기열에 있는 곡들의 리스트
        """
        items = list(self.queue._queue)
        logger.debug(f"[{self.guild.name}] 대기열 조회 - 총 {len(items)}개 항목")
        return items

    def set_volume(self, volume: float) -> float:
        """
        볼륨을 설정합니다.

        Args:
            volume: 설정할 볼륨 (0.0 ~ 2.0)

        Returns:
            설정된 볼륨 값
        """
        self.volume = max(0.0, min(volume, MAX_VOLUME))

        # 현재 재생 중인 경우 볼륨 즉시 적용
        if self.voice_client and self.voice_client.source:
            if isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
                self.voice_client.source.volume = self.volume

        logger.info(f"[{self.guild.name}] 볼륨 설정: {self.volume:.0%}")
        return self.volume

    def toggle_repeat(self) -> RepeatMode:
        """
        반복 모드를 순환합니다. (OFF -> ALL -> ONE -> OFF)

        Returns:
            변경된 반복 모드
        """
        if self.repeat_mode == RepeatMode.OFF:
            self.repeat_mode = RepeatMode.ALL
        elif self.repeat_mode == RepeatMode.ALL:
            self.repeat_mode = RepeatMode.ONE
        else:
            self.repeat_mode = RepeatMode.OFF

        logger.info(f"[{self.guild.name}] 반복 모드 변경: {self.repeat_mode.name}")
        return self.repeat_mode

    def toggle_shuffle(self) -> bool:
        """
        셔플을 토글합니다.

        Returns:
            셔플 활성화 여부
        """
        self.shuffle = not self.shuffle
        logger.info(f"[{self.guild.name}] 셔플 {'활성화' if self.shuffle else '비활성화'}")
        return self.shuffle

    def shuffle_queue(self) -> int:
        """
        대기열을 셔플합니다.

        Returns:
            셔플된 곡 수
        """
        items = self.get_queue_items()
        if len(items) < 2:
            return 0

        random.shuffle(items)

        # 대기열 재구성
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        for item in items:
            self.queue.put_nowait(item)

        logger.info(f"[{self.guild.name}] 대기열 셔플 완료: {len(items)}곡")
        return len(items)

    async def pause(self) -> bool:
        """
        재생을 일시정지합니다.

        Returns:
            일시정지 성공 여부
        """
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.paused = True
            logger.info(f"[{self.guild.name}] 재생 일시정지")
            return True
        return False

    async def resume(self) -> bool:
        """
        재생을 재개합니다.

        Returns:
            재개 성공 여부
        """
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.paused = False
            logger.info(f"[{self.guild.name}] 재생 재개")
            return True
        return False

    async def _load_next_playlist_batch(self) -> None:
        """
        플레이리스트의 다음 배치를 자동으로 로드합니다 (lazy loading).

        대기열에 곡이 부족할 때 자동으로 호출되어
        플레이리스트의 다음 곡들을 미리 로드합니다.
        """
        # 이미 로딩 중이거나 플레이리스트 URL이 없으면 스킵
        if not self.current_playlist_url or self.loading_next_batch:
            logger.debug(
                f"[{self.guild.name}] 배치 로딩 스킵 - "
                f"URL 존재: {bool(self.current_playlist_url)}, "
                f"로딩 중: {self.loading_next_batch}"
            )
            return

        self.loading_next_batch = True
        logger.info(
            f"[{self.guild.name}] 플레이리스트 배치 로딩 시작 - "
            f"시작 인덱스: {self.next_playlist_index}"
        )

        from ytdl_source import YTDLSource

        try:
            entries = await YTDLSource.create_source(
                self.current_playlist_url,
                loop=self.bot.loop,
                get_next_batch=True,
                playlist_start_index=self.next_playlist_index
            )

            if not entries or not isinstance(entries, list):
                logger.info(
                    f"[{self.guild.name}] 플레이리스트 로딩 완료 - "
                    "더 이상 로드할 항목 없음"
                )
                self.current_playlist_url = None
                return

            # 각 항목을 대기열에 추가
            added = 0
            for entry in entries:
                if not is_valid_entry(entry):
                    logger.debug(
                        f"[{self.guild.name}] 유효하지 않은 항목 스킵 - "
                        f"제목: {entry.get('title', '알 수 없음')}"
                    )
                    continue

                try:
                    source = create_ffmpeg_source(
                        entry,
                        self.playlist_requester or "자동 로드",
                        FFMPEG_OPTIONS
                    )
                    await self.queue.put(source)
                    added += 1
                    logger.debug(
                        f"[{self.guild.name}] 대기열에 곡 추가 - "
                        f"제목: '{source.title}'"
                    )
                except Exception as e:
                    logger.error(
                        f"[{self.guild.name}] FFmpeg 소스 생성 실패 - "
                        f"제목: {entry.get('title', '알 수 없음')}, 오류: {e}"
                    )

            if added > 0:
                self.next_playlist_index += added
                logger.info(
                    f"[{self.guild.name}] 플레이리스트 배치 로딩 완료 - "
                    f"추가된 곡: {added}개, 다음 인덱스: {self.next_playlist_index}"
                )
            else:
                logger.warning(
                    f"[{self.guild.name}] 배치에서 유효한 곡을 찾지 못함 - "
                    "플레이리스트 로딩 중단"
                )
                self.current_playlist_url = None

        except Exception as e:
            logger.error(
                f"[{self.guild.name}] 플레이리스트 배치 로딩 오류 - {e}",
                exc_info=True
            )
            self.current_playlist_url = None
        finally:
            self.loading_next_batch = False

    async def player_loop(self) -> None:
        """
        메인 재생 루프입니다.

        대기열에서 곡을 가져와 재생하고,
        채널 상태를 모니터링하며,
        필요시 플레이리스트 lazy loading을 트리거합니다.
        """
        await self.bot.wait_until_ready()
        logger.info(
            f"[{self.guild.name}] 재생 루프 시작 - "
            f"초기 대기열 크기: {self.queue.qsize()}"
        )

        while True:
            self.next.clear()

            # 현재 상태 로깅
            logger.debug(
                f"[{self.guild.name}] 재생 루프 반복 - "
                f"대기열: {self.queue.qsize()}개, "
                f"현재곡: {getattr(self.current, 'title', '없음')}"
            )

            # Lazy loading 트리거 체크
            queue_size = self.queue.qsize()
            if (queue_size < LAZY_LOAD_THRESHOLD
                    and self.current_playlist_url
                    and not self.loading_next_batch):
                logger.debug(
                    f"[{self.guild.name}] Lazy loading 트리거 - "
                    f"대기열 {queue_size}개 < 임계값 {LAZY_LOAD_THRESHOLD}"
                )
                asyncio.create_task(self._load_next_playlist_batch())

            # 음성 클라이언트 연결 상태 확인
            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning(
                    f"[{self.guild.name}] 음성 클라이언트 연결 끊김 - 재생 루프 종료"
                )
                await self.destroy(notify=False)
                return

            # 채널에 사용자가 없는지 확인
            members = [m for m in self.voice_client.channel.members if not m.bot]
            logger.debug(
                f"[{self.guild.name}] 음성 채널 멤버 수: {len(members)}명 (봇 제외)"
            )

            if not members:
                await self._handle_empty_channel()
                if not self.voice_client or not self.voice_client.is_connected():
                    return
                continue

            # 다음 곡 결정
            next_song = await self._get_next_song()
            if next_song is None:
                return  # 타임아웃 또는 취소

            if next_song is False:
                continue  # 곡 없음, 다시 시도

            # 곡 재생
            await self._play_song(next_song)
            await self.next.wait()

            # 재생이 완전히 끝날 때까지 대기
            while self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                await asyncio.sleep(0.2)

    async def _get_next_song(self) -> Any:
        """
        다음 재생할 곡을 결정합니다.

        Returns:
            - 다음 곡 객체
            - None: 타임아웃 또는 취소
            - False: 곡 없음, 다시 시도 필요
        """
        # 한 곡 반복 모드
        if self.repeat_mode == RepeatMode.ONE and self.current:
            logger.debug(f"[{self.guild.name}] 한 곡 반복 모드 - 현재 곡 다시 재생")
            # 현재 곡의 새 소스 생성 필요 (FFmpeg 소스는 재사용 불가)
            try:
                new_source = create_ffmpeg_source(
                    {
                        "url": self.current.url if hasattr(self.current, 'url') else "",
                        "title": self.current.title,
                        "webpage_url": getattr(self.current, 'webpage_url', ''),
                        "duration": getattr(self.current, 'duration', None),
                        "thumbnail": getattr(self.current, 'thumbnail', None),
                    },
                    getattr(self.current, 'requester', '알 수 없음'),
                    FFMPEG_OPTIONS
                )
                return new_source
            except Exception as e:
                logger.error(f"[{self.guild.name}] 한 곡 반복 소스 생성 실패: {e}")
                self.repeat_mode = RepeatMode.OFF

        # 전체 반복 모드 - 대기열이 비면 히스토리에서 다시 로드
        if self.repeat_mode == RepeatMode.ALL and self.queue.empty() and self.history:
            logger.debug(f"[{self.guild.name}] 전체 반복 모드 - 히스토리에서 대기열 복원")
            for item in self.history:
                try:
                    new_source = create_ffmpeg_source(
                        {
                            "url": item.get('url', ''),
                            "title": item.get('title', '알 수 없음'),
                            "webpage_url": item.get('webpage_url', ''),
                            "duration": item.get('duration'),
                            "thumbnail": item.get('thumbnail'),
                        },
                        item.get('requester', '알 수 없음'),
                        FFMPEG_OPTIONS
                    )
                    await self.queue.put(new_source)
                except Exception as e:
                    logger.error(f"[{self.guild.name}] 히스토리 복원 실패: {e}")
            self.history.clear()

        # 대기열에서 다음 곡 가져오기
        try:
            logger.debug(
                f"[{self.guild.name}] 대기열에서 다음 곡 대기 중 "
                f"(타임아웃: {QUEUE_TIMEOUT}초)"
            )
            next_song = await asyncio.wait_for(
                self.queue.get(),
                timeout=QUEUE_TIMEOUT
            )

            # 히스토리에 저장 (전체 반복용)
            if self.repeat_mode == RepeatMode.ALL:
                self.history.append({
                    'url': getattr(next_song, 'url', ''),
                    'title': getattr(next_song, 'title', '알 수 없음'),
                    'webpage_url': getattr(next_song, 'webpage_url', ''),
                    'duration': getattr(next_song, 'duration', None),
                    'thumbnail': getattr(next_song, 'thumbnail', None),
                    'requester': getattr(next_song, 'requester', '알 수 없음'),
                })

            logger.debug(
                f"[{self.guild.name}] 대기열에서 곡 가져옴 - "
                f"제목: '{getattr(next_song, 'title', '알 수 없음')}'"
            )
            return next_song

        except asyncio.TimeoutError:
            logger.info(
                f"[{self.guild.name}] 대기열 타임아웃 ({QUEUE_TIMEOUT}초) - "
                "음성 채널 연결 종료"
            )
            await self.text_channel.send(
                embed=make_embed(
                    f"{Emoji.DISCONNECT} 대기열이 {QUEUE_TIMEOUT // 60}분 동안 비어있어 "
                    "연결을 종료합니다.",
                    Colors.WARNING
                )
            )
            await self.destroy(notify=False)
            return None

        except asyncio.CancelledError:
            logger.info(f"[{self.guild.name}] 재생 루프 태스크 취소됨")
            return None

    async def _handle_empty_channel(self) -> None:
        """
        음성 채널에 사용자가 없을 때 처리합니다.

        지정된 시간 동안 대기 후에도 사용자가 없으면
        음성 채널 연결을 종료합니다.
        """
        logger.info(
            f"[{self.guild.name}] 음성 채널에 사용자 없음 - "
            f"{IDLE_TIMEOUT}초 대기 후 연결 종료 예정"
        )
        await self.text_channel.send(
            embed=make_embed(
                f"{Emoji.PAUSE} 음성 채널에 아무도 없습니다. "
                f"{IDLE_TIMEOUT}초 후 연결을 종료합니다.",
                Colors.WARNING
            )
        )

        await asyncio.sleep(IDLE_TIMEOUT)

        # 타이머 후 상태 재확인
        if not self.voice_client or not self.voice_client.is_connected():
            logger.debug(f"[{self.guild.name}] 대기 중 이미 연결 종료됨")
            return

        members = [m for m in self.voice_client.channel.members if not m.bot]
        if not members:
            logger.info(
                f"[{self.guild.name}] {IDLE_TIMEOUT}초 경과 후에도 사용자 없음 - "
                "음성 채널 연결 종료"
            )
            await self.destroy(notify=True)
        else:
            logger.info(
                f"[{self.guild.name}] 대기 중 사용자 재접속 - "
                f"현재 {len(members)}명, 재생 계속"
            )

    async def _play_song(self, song: Any) -> None:
        """
        곡을 재생하고 재생 오류를 처리합니다.

        Args:
            song: 재생할 FFmpegPCMAudio 객체
        """
        title = getattr(song, 'title', '알 수 없음')
        duration = getattr(song, 'duration', None)
        requester = getattr(song, 'requester', '알 수 없음')

        logger.info(
            f"[{self.guild.name}] 곡 재생 시작 - "
            f"제목: '{title}', 길이: {format_time(duration)}, 요청자: {requester}"
        )

        self.current = song
        self.paused = False

        try:
            # 볼륨 조절을 위한 PCMVolumeTransformer 적용
            volume_source = discord.PCMVolumeTransformer(song, volume=self.volume)

            self.voice_client.play(
                volume_source,
                after=lambda e: self.bot.loop.call_soon_threadsafe(
                    self._playback_finished, e
                )
            )
            self.start_time = self.bot.loop.time()

            # 봇 상태 업데이트
            await self._update_presence()

            # 현재 재생 중 임베드 전송
            await self.text_channel.send(embed=self.build_now_playing_embed())
            logger.debug(f"[{self.guild.name}] '현재 재생 중' 메시지 전송 완료")

        except discord.ClientException as e:
            logger.error(
                f"[{self.guild.name}] 재생 실패 (ClientException) - "
                f"제목: '{title}', 오류: {e}"
            )
            await self.text_channel.send(embed=make_error_embed(f"재생 오류: {e}"))
            self._reset_current()

        except Exception as e:
            logger.error(
                f"[{self.guild.name}] 재생 실패 (예기치 않은 오류) - "
                f"제목: '{title}', 오류: {e}",
                exc_info=True
            )
            await self.text_channel.send(embed=make_error_embed(f"예기치 않은 재생 오류: {e}"))
            self._reset_current()

    async def _update_presence(self) -> None:
        """봇의 상태 메시지를 현재 재생 중인 곡으로 업데이트합니다."""
        if self.current:
            title = truncate_string(getattr(self.current, 'title', '음악'), 40)
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=title
            )
            await self.bot.change_presence(activity=activity)

    def _reset_current(self) -> None:
        """현재 곡 상태를 초기화하고 다음 곡으로 진행합니다."""
        self.current = None
        self.paused = False
        self.bot.loop.call_soon_threadsafe(self.next.set)
        logger.debug(f"[{self.guild.name}] 현재 곡 상태 초기화 및 다음 곡 신호 전송")

    def _playback_finished(self, error: Optional[Exception]) -> None:
        """
        FFmpeg 재생 완료 콜백입니다.

        Args:
            error: 재생 중 발생한 오류 (없으면 None)
        """
        title = getattr(self.current, 'title', '알 수 없음')

        if error:
            logger.error(
                f"[{self.guild.name}] 재생 중 오류 발생 - "
                f"제목: '{title}', 오류: {error}"
            )
            asyncio.run_coroutine_threadsafe(
                self.text_channel.send(embed=make_error_embed(f"재생 중 오류: {error}")),
                self.bot.loop
            )
        else:
            logger.info(f"[{self.guild.name}] 곡 재생 완료 - 제목: '{title}'")

        # 한 곡 반복이 아닌 경우에만 current 초기화
        if self.repeat_mode != RepeatMode.ONE:
            if self.voice_client and not self.voice_client.is_playing():
                self.current = None
        self.next.set()

    def build_now_playing_embed(self) -> discord.Embed:
        """
        현재 재생 중인 곡의 정보 임베드를 생성합니다.

        Returns:
            곡 정보가 포함된 Discord Embed 객체
        """
        if not self.current:
            return make_embed(f"{Emoji.ERROR} 현재 재생 중인 곡이 없습니다.", Colors.ERROR)

        title = getattr(self.current, 'title', '알 수 없음')
        url = getattr(self.current, 'webpage_url', '')
        requester = getattr(self.current, 'requester', '알 수 없음')
        duration = getattr(self.current, 'duration', None)
        thumbnail = getattr(self.current, 'thumbnail', None)

        embed = discord.Embed(
            title=f"{Emoji.MUSIC} 현재 재생 중",
            color=Colors.MUSIC
        )

        # 곡 정보
        description = f"**[{truncate_string(title, 50)}]({url})**\n\n"

        # 재생 정보
        if duration:
            description += f"{Emoji.TIME} `{format_time(duration)}`\n"

        description += f"{Emoji.USER} {requester}\n"

        # 재생 설정 상태
        status_parts = []
        status_parts.append(f"{Emoji.VOLUME_HIGH} `{self.volume:.0%}`")

        if self.repeat_mode == RepeatMode.ONE:
            status_parts.append(f"{Emoji.REPEAT_ONE} 한곡")
        elif self.repeat_mode == RepeatMode.ALL:
            status_parts.append(f"{Emoji.REPEAT} 전체")

        if self.shuffle:
            status_parts.append(f"{Emoji.SHUFFLE} 셔플")

        description += " ".join(status_parts)

        embed.description = description

        # 썸네일 추가
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # 대기열 정보
        queue_size = self.queue.qsize()
        if queue_size > 0:
            embed.set_footer(text=f"대기열에 {queue_size}곡 있음")

        logger.debug(f"[{self.guild.name}] 현재 재생 중 임베드 생성 - 제목: '{title}'")
        return embed

    def build_progress_embed(self) -> discord.Embed:
        """
        진행률이 포함된 현재 재생 중 임베드를 생성합니다.

        Returns:
            진행률 바가 포함된 Discord Embed 객체
        """
        embed = self.build_now_playing_embed()

        playback_time = self.get_playback_time()
        duration = getattr(self.current, 'duration', None) if self.current else None

        if duration and playback_time is not None:
            progress_bar = create_progress_bar(playback_time, duration, 12)
            embed.add_field(
                name="진행률",
                value=f"`{format_time(playback_time)}` {progress_bar} `{format_time(duration)}`",
                inline=False
            )

        return embed

    def get_playback_time(self) -> Optional[float]:
        """
        현재 재생 위치를 초 단위로 반환합니다.

        Returns:
            재생 위치 (초), 재생 중이 아니면 None
        """
        if not self.current or self.start_time is None:
            return None

        elapsed = self.bot.loop.time() - self.start_time
        duration = getattr(self.current, 'duration', None)

        if duration is not None:
            return min(elapsed, duration)
        return elapsed

    def clear_queue(self) -> int:
        """
        대기열을 비우고 플레이리스트 상태를 초기화합니다.

        Returns:
            제거된 곡 수
        """
        count = self.queue.qsize()

        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.history.clear()
        self.current_playlist_url = None
        self.next_playlist_index = 1
        self.loading_next_batch = False

        logger.info(f"[{self.guild.name}] 대기열 비움 - 제거된 항목: {count}개")
        return count

    async def destroy(self, notify: bool = True) -> None:
        """
        플레이어를 정리하고 음성 연결을 종료합니다.

        Args:
            notify: 종료 메시지를 텍스트 채널에 보낼지 여부
        """
        guild_name = self.guild.name
        logger.info(
            f"[{guild_name}] 플레이어 파괴 시작 - "
            f"알림: {notify}, 대기열: {self.queue.qsize()}개, "
            f"현재곡: {getattr(self.current, 'title', '없음')}"
        )

        # 재생 중지
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            logger.debug(f"[{guild_name}] 현재 재생 중지됨")

        # 대기열 및 상태 초기화
        self.clear_queue()
        self.current = None
        self.paused = False

        # 봇 상태 초기화
        try:
            await self.bot.change_presence(activity=None)
        except Exception:
            pass

        # 재생 루프 태스크 취소
        if self.player_task and not self.player_task.done():
            self.player_task.cancel()
            logger.debug(f"[{guild_name}] 재생 루프 태스크 취소 요청")
            try:
                await self.player_task
            except asyncio.CancelledError:
                logger.debug(f"[{guild_name}] 재생 루프 태스크 정상 취소됨")
            except Exception as e:
                logger.error(
                    f"[{guild_name}] 재생 루프 태스크 대기 중 오류 - {e}"
                )

        # 음성 연결 종료
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
            logger.debug(f"[{guild_name}] 음성 채널 연결 해제됨")

        self.voice_client = None

        # 봇의 플레이어 목록에서 제거
        if self.guild.id in self.bot.music_players:
            del self.bot.music_players[self.guild.id]
            logger.debug(f"[{guild_name}] 봇 플레이어 목록에서 제거됨")

        # 종료 알림 메시지
        if notify:
            try:
                await self.text_channel.send(
                    embed=make_embed(
                        f"{Emoji.DISCONNECT} 음악 재생을 종료하고 음성 채널을 나갑니다.",
                        Colors.INFO
                    )
                )
                logger.debug(f"[{guild_name}] 종료 알림 메시지 전송됨")
            except Exception as e:
                logger.warning(
                    f"[{guild_name}] 종료 알림 메시지 전송 실패 - {e}"
                )

        logger.info(f"[{guild_name}] 플레이어 파괴 완료")
