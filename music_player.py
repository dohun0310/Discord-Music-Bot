import asyncio
import discord
import time
from utils import make_embed

def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

class MusicPlayer:
    def __init__(self, guild: discord.Guild, text_channel: discord.TextChannel, voice_client: discord.VoiceClient, bot: discord.ext.commands.Bot):
        self.guild = guild
        self.text_channel = text_channel
        self.voice_client = voice_client
        self.bot = bot
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current = None
        self.player_task = self.bot.loop.create_task(self.player_loop())

    def get_queue_items(self) -> list[discord.FFmpegPCMAudio]:
        return list(self.queue._queue)

    async def player_loop(self):
        try:
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                if len(self.voice_client.channel.members) <= 1:
                    await self.text_channel.send(embed=make_embed("💤 음성 채널에 아무도 없습니다. 연결을 종료합니다."))
                    await self.destroy()
                    return

                self.next.clear()
                if self.queue.empty():
                    await self.text_channel.send(embed=make_embed("🎵 대기열이 비어있습니다. 30초 동안 기다립니다."))
                    try:
                        self.current = await asyncio.wait_for(self.queue.get(), timeout=30)
                    except asyncio.TimeoutError:
                        await self.text_channel.send(embed=make_embed("🎵 대기열이 비어 연결을 종료합니다."))
                        await self.destroy()
                        return
                else:
                    self.current = await self.queue.get()

                start_time = time.time()
                self.voice_client.play(self.current, after=lambda e, **_: self.bot.loop.call_soon_threadsafe(self.next.set))
                progress_message = await self.text_channel.send(embed=make_embed(
                    f"🎶 현재 재생: [**{self.current.title}**]({getattr(self.current, 'webpage_url', 'https://www.youtube.com/')})"
                ))
                while not self.next.is_set():
                    elapsed = time.time() - start_time
                    duration = getattr(self.current, "duration", None)
                    if duration is not None:
                        progress_str = f"[{format_time(elapsed)} / {format_time(duration)}]"
                    else:
                        progress_str = f"[{format_time(elapsed)} / --:--]"
                    new_embed = make_embed(
                        f"🎶 현재 재생: [**{self.current.title}**]({getattr(self.current, 'webpage_url', 'https://www.youtube.com/')}) {progress_str}"
                    )
                    await progress_message.edit(embed=new_embed)
                    await asyncio.sleep(5)
                await progress_message.delete()
        except asyncio.CancelledError:
            return

    def clear_queue(self):
        """대기열에 남은 트랙을 모두 제거합니다."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def destroy(self):
        if self.voice_client.is_playing():
            self.voice_client.stop()
        self.current = None
        self.clear_queue()
        self.player_task.cancel()
        try:
            await self.player_task
        except asyncio.CancelledError:
            pass
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
        if self.guild.id in self.bot.music_players:
            del self.bot.music_players[self.guild.id]