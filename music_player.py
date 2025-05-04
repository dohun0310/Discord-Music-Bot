import asyncio
import discord
import logging
from typing import Optional, List

from utils import make_embed

logger = logging.getLogger('discord.bot.player')

def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

class MusicPlayer:
    def __init__(self, guild: discord.Guild, text_channel: discord.TextChannel, voice_client: discord.VoiceClient, bot: discord.ext.commands.Bot):
        self.guild = guild
        self.text_channel = text_channel
        self.voice_client = voice_client
        self.bot = bot
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current: Optional[discord.FFmpegPCMAudio] = None
        self.player_task = self.bot.loop.create_task(self.player_loop())
        self.start_time: Optional[float] = None

        self.current_playlist_url: Optional[str] = None
        self.next_playlist_index: int = 1
        self.loading_next_batch: bool = False
        self.playlist_requester: Optional[str] = None

        self.player_task = self.bot.loop.create_task(self.player_loop())
        logger.info(f"[{self.guild.name}] MusicPlayer 초기화 및 player_loop 시작됨.")

    def get_queue_items(self) -> List[discord.FFmpegPCMAudio]:
        return list(self.queue._queue)

    async def _load_next_playlist_batch(self):
        if not self.current_playlist_url or self.loading_next_batch:
            return

        self.loading_next_batch = True
        logger.info(f"[{self.guild.name}] 플레이리스트 다음 배치 로딩 시작: URL={self.current_playlist_url}, 시작 인덱스={self.next_playlist_index}")

        from ytdl_source import YTDLSource
        from config import FFMPEG_OPTIONS

        try:
            next_entries = await YTDLSource.create_source(
                self.current_playlist_url,
                loop=self.bot.loop,
                get_next_batch=True,
                playlist_start_index=self.next_playlist_index
            )

            added_count = 0
            if next_entries and isinstance(next_entries, list):
                for entry in next_entries:
                    if not all(key in entry for key in ("url", "title", "webpage_url")):
                        logger.warning(f"[{self.guild.name}] 자동 로드된 항목 키 누락: {entry.get('title')}")
                        continue
                    try:
                        source = discord.FFmpegPCMAudio(entry['url'], **FFMPEG_OPTIONS)
                        source.title = entry['title']
                        source.webpage_url = entry.get('webpage_url', '')
                        source.duration = entry.get('duration')

                        source.requester = self.playlist_requester or "자동 로드"
                        await self.queue.put(source)
                        added_count += 1
                    except Exception as e:
                        logger.error(f"[{self.guild.name}] 자동 로드 FFmpegPCMAudio 생성 실패: {entry.get('title')}, 오류: {e}")
                        continue

                if added_count > 0:
                    self.next_playlist_index += added_count
                    logger.info(f"[{self.guild.name}] {added_count}개의 곡 자동 로드 완료. 다음 시작 인덱스: {self.next_playlist_index}")
                else:
                    logger.info(f"[{self.guild.name}] 플레이리스트 '{self.current_playlist_url}'의 모든 곡 로드 완료.")
                    self.current_playlist_url = None
            else:
                logger.info(f"[{self.guild.name}] 플레이리스트 '{self.current_playlist_url}' 로드할 다음 항목 없음 또는 오류.")
                self.current_playlist_url = None

        except Exception as e:
            logger.error(f"[{self.guild.name}] 다음 배치 로딩 중 예외 발생: {e}", exc_info=True)
            self.current_playlist_url = None
        finally:
            self.loading_next_batch = False

    async def player_loop(self):
        await self.bot.wait_until_ready()
        logger.info(f"[{self.guild.name}] player_loop 시작됨.")

        while True:
            self.next.clear()

            LAZY_LOAD_THRESHOLD = 3
            if self.queue.qsize() < LAZY_LOAD_THRESHOLD and self.current_playlist_url and not self.loading_next_batch:
                asyncio.create_task(self._load_next_playlist_batch())

            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning(f"[{self.guild.name}] player_loop: 음성 클라이언트 연결 끊김. 루프 종료.")
                await self.destroy(notify=False)
                return

            if len(self.voice_client.channel.members) <= 1:
                logger.info(f"[{self.guild.name}] 음성 채널에 아무도 없어 60초 후 연결 종료 타이머 시작.")
                await self.text_channel.send(embed=make_embed("💤 음성 채널에 아무도 없습니다. 60초 후 연결을 종료합니다."))

                await asyncio.sleep(60)
                if not self.voice_client or not self.voice_client.is_connected():
                    return
                if len(self.voice_client.channel.members) <= 1:
                    logger.info(f"[{self.guild.name}] 60초 경과, 여전히 혼자이므로 연결 종료.")
                    await self.destroy(notify=False)
                    return
                else:
                    logger.info(f"[{self.guild.name}] 60초 타이머 중 유저 재입장. 재생 계속.")

            try:
                next_song = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                logger.info(f"[{self.guild.name}] 300초 동안 대기열에 새 곡이 없어 연결을 종료합니다.")
                await self.text_channel.send(embed=make_embed("🎵 대기열이 오랫동안 비어 연결을 종료합니다."))
                await self.destroy(notify=False)
                return
            except asyncio.CancelledError:
                logger.info(f"[{self.guild.name}] player_loop 태스크 취소됨.")
                return

            if next_song:
                logger.info(f"[{self.guild.name}] 다음 곡 재생 시작: {getattr(next_song, 'title', '알 수 없는 곡')}")
                try:
                    self.voice_client.play(next_song, after=lambda e: self.bot.loop.call_soon_threadsafe(self._playback_finished, e))
                    self.current = next_song
                    self.start_time = self.bot.loop.time()
                    await self.text_channel.send(embed=self.build_now_playing_embed())
                except discord.ClientException as e:
                    logger.error(f"[{self.guild.name}] 음원 재생 실패 (ClientException): {e}")
                    await self.text_channel.send(embed=make_embed(f"⚠️ 음원 재생 중 오류 발생: {e}"))
                    self.current = None
                    self.bot.loop.call_soon_threadsafe(self.next.set)
                except Exception as e:
                    logger.error(f"[{self.guild.name}] 음원 재생 중 예외 발생: {e}", exc_info=True)
                    await self.text_channel.send(embed=make_embed(f"⚠️ 예상치 못한 재생 오류 발생: {e}"))
                    self.current = None
                    self.bot.loop.call_soon_threadsafe(self.next.set)

                await self.next.wait()
                while self.voice_client.is_playing() or self.current is not None:
                    await asyncio.sleep(0.2)

    def _playback_finished(self, error):
        if error:
            logger.error(f"[{self.guild.name}] 재생 중 오류 발생 (after callback): {error}")
            asyncio.run_coroutine_threadsafe(self.text_channel.send(embed=make_embed(f"⚠️ 재생 중 오류: {error}")), self.bot.loop)
            self.current = None
        else:
            logger.info(f"[{self.guild.name}] 곡 재생 완료: {getattr(self.current, 'title', '알 수 없는 곡')}")
        self.next.set()


    def build_now_playing_embed(self) -> discord.Embed:
        if not self.current:
            return make_embed("🚫 현재 재생 중인 곡이 없습니다.")

        title = getattr(self.current, 'title', '알 수 없는 곡')
        url = getattr(self.current, 'webpage_url', '')
        requester = getattr(self.current, 'requester', '알 수 없음')
        duration = getattr(self.current, 'duration', None)

        embed = discord.Embed(title="🎶 현재 재생 중", color=discord.Color.purple())
        description = f"[**{title}**]({url})\n"
        if duration:
            description += f"길이: `{format_time(duration)}`\n"
        description += f"요청: {requester}"
        embed.description = description
        return embed
    
    def get_playback_time(self) -> Optional[float]:
        if not self.current or self.start_time is None:
            return None
        elapsed = self.bot.loop.time() - self.start_time

        duration = getattr(self.current, 'duration', None)
        if duration is not None:
            return min(elapsed, duration)
        return elapsed

    def clear_queue(self):
        count = self.queue.qsize()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        logger.info(f"[{self.guild.name}] 대기열 비움 ({count}개 항목 제거).")

        self.current_playlist_url = None
        self.next_playlist_index = 1
        self.loading_next_batch = False

    async def destroy(self, notify: bool = True):
        guild_name = self.guild.name
        logger.info(f"[{guild_name}] 플레이어 파괴 시작...")

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            logger.info(f"[{guild_name}] 음원 재생 중지됨.")

        self.clear_queue()
        self.current = None

        if self.player_task and not self.player_task.done():
            self.player_task.cancel()
            logger.info(f"[{guild_name}] player_loop 태스크 취소 요청됨.")
            try:
                await self.player_task
            except asyncio.CancelledError:
                logger.info(f"[{guild_name}] player_loop 태스크 정상적으로 취소됨.")
            except Exception as e:
                 logger.error(f"[{guild_name}] player_loop 태스크 대기 중 오류: {e}", exc_info=True)

        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
            logger.info(f"[{guild_name}] 음성 클라이언트 연결 해제됨.")

        self.voice_client = None

        if self.guild.id in self.bot.music_players:
            del self.bot.music_players[self.guild.id]
            logger.info(f"[{guild_name}] 봇 플레이어 목록에서 제거됨.")

        if notify:
            try:
                await self.text_channel.send(embed=make_embed("👋 음악 재생을 종료하고 음성 채널을 나갑니다."))
            except Exception as e:
                 logger.warning(f"[{guild_name}] 플레이어 파괴 알림 메시지 전송 실패: {e}")

        logger.info(f"[{guild_name}] 플레이어 파괴 완료.")