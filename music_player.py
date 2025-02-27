import asyncio
import discord
from utils import make_embed
from config import FFMPEG_OPTIONS

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

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            if len(self.voice_client.channel.members) <= 1:
                await self.text_channel.send(embed=make_embed("💤 음성 채널에 아무도 없습니다. 연결을 종료합니다."))
                await self.destroy()
                return

            self.next.clear()
            try:
                self.current = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await self.text_channel.send(embed=make_embed("⌛ 5분 동안 대기열이 없어 연결을 종료합니다."))
                await self.destroy()
                return

            if len(self.voice_client.channel.members) <= 1:
                await self.text_channel.send(embed=make_embed("💤 음성 채널에 아무도 없습니다. 연결을 종료합니다."))
                await self.destroy()
                return

            self.voice_client.play(self.current, after=lambda e: self.bot.loop.call_soon_threadsafe(self.next.set))
            msg = f"🎶 현재 재생: **{self.current.title}**\n[바로가기]({getattr(self.current, 'webpage_url', 'https://www.youtube.com/')})"
            await self.text_channel.send(embed=make_embed(msg), delete_after=60)
            await self.next.wait()
            
            if self.queue.empty():
                await self.text_channel.send(embed=make_embed("🎵 노래가 끝났습니다. 5분 후에 연결을 종료합니다."))
            
            self.current = None

    async def destroy(self):
        self.queue = asyncio.Queue()
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
        if self.guild.id in self.bot.music_players:
            del self.bot.music_players[self.guild.id]