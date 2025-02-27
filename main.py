import discord
from discord.ext import commands
from discord import app_commands
import asyncio

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

async def get_player(interaction: discord.Interaction):
    if interaction.guild.id in bot.music_players:
        return bot.music_players[interaction.guild.id]
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
        return None
    channel = interaction.user.voice.channel
    voice_client = await channel.connect()
    player = MusicPlayer(interaction.guild, interaction.channel, voice_client, bot)
    bot.music_players[interaction.guild.id] = player
    return player

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
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return
    loop = bot.loop
    try:
        data = await YTDLSource.create_source(query, loop=loop)
    except (ValueError, TypeError) as e:
        await send_temp(interaction, make_embed("❗ 검색 결과가 없습니다."))
        return
    if not data or "url" not in data or "title" not in data:
        await send_temp(interaction, make_embed("❗ 검색 결과가 없습니다."))
        return
    source = discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS)
    source.title = data['title']
    source.webpage_url = data['webpage_url']
    await player.queue.put(source)
    msg = f"✅ 대기열에 추가됨: [**{data['title']}**]({data['webpage_url']})"
    await send_temp(interaction, make_embed(msg))

@bot.tree.command(name="대기열", description="현재 대기열을 확인합니다.")
async def 대기열(interaction: discord.Interaction):
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return
    msg = ""
    if player.current:
        msg += f"🎵 현재 재생: [**{player.current.title}**]({getattr(player.current, 'webpage_url', 'https://www.youtube.com/')})\n"
    if player.queue.empty():
        msg += "📭 대기열이 비어있습니다."
    else:
        queue_list = list(player.queue._queue)
        for i, song in enumerate(queue_list, 1):
            msg += f"{i}. [**{song.title}**]({getattr(song, 'webpage_url', 'https://www.youtube.com/')})\n"
    await send_temp(interaction, make_embed(msg))

@bot.tree.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
@app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
async def 삭제(interaction: discord.Interaction, position: int):
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=False)
    player = await get_player(interaction)
    if player is None:
        return
    if player.queue.empty():
        await send_temp(interaction, make_embed("📭 대기열이 비어있습니다."))
        return
    queue_list = list(player.queue._queue)
    if position < 1 or position > len(queue_list):
        await send_temp(interaction, make_embed("❗ 유효하지 않은 순번입니다."))
        return
    removed = queue_list.pop(position - 1)
    new_queue = asyncio.Queue()
    for song in queue_list:
        await new_queue.put(song)
    player.queue = new_queue
    msg = f"🗑️ 제거됨: **{removed.title}**"
    await send_temp(interaction, make_embed(msg))

@bot.tree.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
async def 스킵(interaction: discord.Interaction):
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
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

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    # 오류 메시지가 사라지지 않도록 일반 메시지로 전송합니다.
    if interaction.response.is_done():
        await interaction.followup.send(embed=make_embed(f"❗ 오류가 발생했습니다 오류 내용: {error}"))
    else:
        await interaction.response.send_message(embed=make_embed(f"오류 내용: {error}"))
        
bot.run(BOT_TOKEN)