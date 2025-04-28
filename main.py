import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Optional

from config import BOT_TOKEN, FFMPEG_OPTIONS
from utils import make_embed, send_temp
from ytdl_source import YTDLSource
from music_player import MusicPlayer

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.music_players = {}

async def get_voice_channel(interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    if interaction.user.voice and interaction.user.voice.channel:
        return interaction.user.voice.channel
    await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
    return None

async def get_player(interaction: discord.Interaction) -> Optional[MusicPlayer]:
    if interaction.guild.id in bot.music_players:
        player = bot.music_players[interaction.guild.id]

        if not player.voice_client or not player.voice_client.is_connected():
            channel = await get_voice_channel(interaction)
            if not channel:
                return None
            player.voice_client = await channel.connect()
        return player

    channel = await get_voice_channel(interaction)
    if not channel:
        return None
    voice_client = await channel.connect()
    player = MusicPlayer(interaction.guild, interaction.channel, voice_client, bot)
    bot.music_players[interaction.guild.id] = player
    return player

async def process_ytdl_data(interaction: discord.Interaction, data, player):
    if isinstance(data, list):
        sources = []
        for entry in data:
            if not all(key in entry for key in ("url", "title", "webpage_url")):
                continue
            try:
                source = discord.FFmpegPCMAudio(entry['url'], **FFMPEG_OPTIONS)
                source.title = entry['title']
                source.webpage_url = entry['webpage_url']
                source.duration = entry.get('duration')
                source.requester = interaction.user.mention
                sources.append(source)
            except Exception:
                continue
        if not sources:
            await send_temp(interaction, make_embed("❗ 유효한 플레이리스트를 찾지 못했습니다."))
            return
        for s in sources:
            await player.queue.put(s)
        msg = f"✅ 플레이리스트에 총 {len(sources)}곡이 추가되었습니다."
        await send_temp(interaction, make_embed(msg))
    else:
        source = discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS)
        source.title = data['title']
        source.webpage_url = data['webpage_url']
        source.duration = data.get('duration')
        source.requester = interaction.user.mention
        await player.queue.put(source)
        msg = f"✅ 대기열에 추가됨: [**{data['title']}**]({data['webpage_url']})"
        await send_temp(interaction, make_embed(msg))

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"동기화된 커맨드 {len(synced)}개.")
    except Exception as e:
        print(e)

@bot.tree.command(name="재생", description="YouTube에서 노래를 재생합니다.")
@app_commands.describe(query="재생할 노래의 제목 또는 URL")
async def 재생(interaction: discord.Interaction, query: str):
    channel = await get_voice_channel(interaction)
    if not channel:
        return
    await interaction.response.defer(ephemeral=False)
    loop = bot.loop
    try:
        data = await YTDLSource.create_source(query, loop=loop)
    except IndexError:
        await send_temp(interaction, make_embed("❗ 검색 결과가 없습니다."))
        return

    if not data or (not isinstance(data, list) and ("url" not in data or "title" not in data)):
        await send_temp(interaction, make_embed("❗ 검색 결과가 없습니다."))
        return

    player = await get_player(interaction)
    if player is None:
        return

    await process_ytdl_data(interaction, data, player)

@bot.tree.command(name="대기열", description="현재 대기열을 확인합니다.")
async def 대기열(interaction: discord.Interaction):
    channel = await get_voice_channel(interaction)
    if not channel:
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return

    msg = ""
    if player.current:
        msg += f"🎵 현재 재생: [**{player.current.title}**]({getattr(player.current, 'webpage_url', 'https://www.youtube.com/')}) - {player.current.requester}\n"

    queue_list = player.get_queue_items()
    if not queue_list:
        msg += "📭 대기열이 비어있습니다."
    else:
        for i, song in enumerate(queue_list, 1):
            msg += f"{i}. [**{song.title}**]({getattr(song, 'webpage_url', 'https://www.youtube.com/')}) - {song.requester}\n"

    await send_temp(interaction, make_embed(msg))

@bot.tree.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
@app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
async def 삭제(interaction: discord.Interaction, position: int):
    channel = await get_voice_channel(interaction)
    if not channel:
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return

    queue_list = player.get_queue_items()
    if not queue_list:
        await send_temp(interaction, make_embed("📭 대기열이 비어있습니다."))
        return
    if position < 1 or position > len(queue_list):
        await send_temp(interaction, make_embed("❗ 유효하지 않은 순번입니다."))
        return

    removed = queue_list.pop(position - 1)
    player.queue = asyncio.Queue()
    for song in queue_list:
        await player.queue.put(song)

    await send_temp(interaction, make_embed(f"🗑️ 제거됨: **{removed.title}**"))

@bot.tree.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
async def 스킵(interaction: discord.Interaction):
    channel = await get_voice_channel(interaction)
    if not channel:
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return
    if player.voice_client.is_playing():
        player.voice_client.stop()
        await send_temp(interaction, make_embed("⏭️ 현재 곡을 건너뛰었습니다."))
    else:
        await send_temp(interaction, make_embed("🚫 재생 중인 곡이 없습니다."))

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member == bot.user:
        if before.channel and before.channel != after.channel:
            guild = member.guild
            if guild.id in bot.music_players:
                player = bot.music_players[guild.id]
                await player.destroy()
        return

    if before.channel and before.channel != after.channel:
        guild_id = member.guild.id
        if guild_id in bot.music_players:
            player = bot.music_players[guild_id]
            vc = player.voice_client
            if vc and vc.channel and len(vc.channel.members) <= 1:
                await player.destroy()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    if interaction.response.is_done():
        await interaction.followup.send(embed=make_embed(f"❗ 오류가 발생했습니다\n오류 내용: {error}"))
    else:
        await interaction.response.send_message(embed=make_embed(f"오류 내용: {error}"))
        
bot.run(BOT_TOKEN)