"""
음악 플레이어 모듈

각 서버(길드)별 음악 재생을 관리합니다.
대기열 관리, 재생 루프, 플레이리스트 lazy loading을 담당합니다.
"""

import asyncio
import logging
from typing import Any, Optional

import discord
from discord.ext import commands

from config import (
    FFMPEG_OPTIONS,
    IDLE_TIMEOUT,
    LAZY_LOAD_THRESHOLD,
    QUEUE_TIMEOUT,
)
from utils import create_ffmpeg_source, format_time, is_valid_entry, make_embed

logger = logging.getLogger('discord.bot.player')


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
        self.next = asyncio.Event()
        self.current: Optional[Any] = None
        self.start_time: Optional[float] = None

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
                logger.debug(
                    f"[{self.guild.name}] 대기열에서 곡 가져옴 - "
                    f"제목: '{getattr(next_song, 'title', '알 수 없음')}'"
                )
            except asyncio.TimeoutError:
                logger.info(
                    f"[{self.guild.name}] 대기열 타임아웃 ({QUEUE_TIMEOUT}초) - "
                    "음성 채널 연결 종료"
                )
                await self.text_channel.send(
                    embed=make_embed(
                        f"🎵 대기열이 {QUEUE_TIMEOUT // 60}분 동안 비어있어 "
                        "연결을 종료합니다."
                    )
                )
                await self.destroy(notify=False)
                return
            except asyncio.CancelledError:
                logger.info(f"[{self.guild.name}] 재생 루프 태스크 취소됨")
                return

            if not next_song:
                continue

            # 곡 재생
            await self._play_song(next_song)
            await self.next.wait()

            # 재생이 완전히 끝날 때까지 대기
            while self.voice_client and (self.voice_client.is_playing() or self.current):
                await asyncio.sleep(0.2)

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
                f"💤 음성 채널에 아무도 없습니다. "
                f"{IDLE_TIMEOUT}초 후 연결을 종료합니다."
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
            await self.destroy(notify=False)
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

        try:
            self.voice_client.play(
                song,
                after=lambda e: self.bot.loop.call_soon_threadsafe(
                    self._playback_finished, e
                )
            )
            self.start_time = self.bot.loop.time()

            await self.text_channel.send(embed=self.build_now_playing_embed())
            logger.debug(f"[{self.guild.name}] '현재 재생 중' 메시지 전송 완료")

        except discord.ClientException as e:
            logger.error(
                f"[{self.guild.name}] 재생 실패 (ClientException) - "
                f"제목: '{title}', 오류: {e}"
            )
            await self.text_channel.send(
                embed=make_embed(f"⚠️ 재생 오류: {e}")
            )
            self._reset_current()

        except Exception as e:
            logger.error(
                f"[{self.guild.name}] 재생 실패 (예기치 않은 오류) - "
                f"제목: '{title}', 오류: {e}",
                exc_info=True
            )
            await self.text_channel.send(
                embed=make_embed(f"⚠️ 예기치 않은 재생 오류: {e}")
            )
            self._reset_current()

    def _reset_current(self) -> None:
        """현재 곡 상태를 초기화하고 다음 곡으로 진행합니다."""
        self.current = None
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
                self.text_channel.send(embed=make_embed(f"⚠️ 재생 중 오류: {error}")),
                self.bot.loop
            )
        else:
            logger.info(f"[{self.guild.name}] 곡 재생 완료 - 제목: '{title}'")

        # 재생이 끝났으면 current 초기화
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
            return make_embed("🚫 현재 재생 중인 곡이 없습니다.")

        title = getattr(self.current, 'title', '알 수 없음')
        url = getattr(self.current, 'webpage_url', '')
        requester = getattr(self.current, 'requester', '알 수 없음')
        duration = getattr(self.current, 'duration', None)

        embed = discord.Embed(title="🎶 현재 재생 중", color=discord.Color.purple())
        description = f"[**{title}**]({url})\n"
        if duration:
            description += f"길이: `{format_time(duration)}`\n"
        description += f"요청: {requester}"
        embed.description = description

        logger.debug(f"[{self.guild.name}] 현재 재생 중 임베드 생성 - 제목: '{title}'")
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

    def clear_queue(self) -> None:
        """대기열을 비우고 플레이리스트 상태를 초기화합니다."""
        count = self.queue.qsize()

        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.current_playlist_url = None
        self.next_playlist_index = 1
        self.loading_next_batch = False

        logger.info(f"[{self.guild.name}] 대기열 비움 - 제거된 항목: {count}개")

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
                    embed=make_embed("👋 음악 재생을 종료하고 음성 채널을 나갑니다.")
                )
                logger.debug(f"[{guild_name}] 종료 알림 메시지 전송됨")
            except Exception as e:
                logger.warning(
                    f"[{guild_name}] 종료 알림 메시지 전송 실패 - {e}"
                )

        logger.info(f"[{guild_name}] 플레이어 파괴 완료")
