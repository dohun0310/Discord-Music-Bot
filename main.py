import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Optional
import logging
import yt_dlp

from config import BOT_TOKEN, FFMPEG_OPTIONS
from utils import make_embed, is_valid_entry, create_ffmpeg_source
from ytdl_source import YTDLSource
from music_player import MusicPlayer, format_time

log_format = '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format)
logging.getLogger('discord').setLevel(logging.WARNING)
player_logger = logging.getLogger('discord.bot.player')
logger = logging.getLogger('discord.bot.main')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.music_players = {}

async def get_voice_channel(interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."), ephemeral=True)
        return None
    return interaction.user.voice.channel

async def get_player(interaction: discord.Interaction) -> Optional[MusicPlayer]:
    guild_id = interaction.guild.id
    player = bot.music_players.get(guild_id)

    if player:
        if not player.voice_client or not player.voice_client.is_connected():
            logger.warning(f"[{interaction.guild.name}] 기존 플레이어의 음성 연결이 끊김. 재연결 시도.")
            channel = await get_voice_channel(interaction)
            if not channel:
                await interaction.followup.send(embed=make_embed("⚠️ 플레이어 재연결 실패: 음성 채널에 접속해주세요."), ephemeral=True)
                await player.destroy(notify=False)
                return None
            try:
                if player.voice_client:
                    await player.voice_client.disconnect(force=True)
                player.voice_client = await channel.connect()
                player.text_channel = interaction.channel
                logger.info(f"[{interaction.guild.name}] 음성 채널 재연결 성공: {channel.name}")
            except Exception as e:
                logger.error(f"[{interaction.guild.name}] 음성 채널 재연결 실패: {e}", exc_info=True)
                await interaction.followup.send(embed=make_embed(f"⚠️ 음성 채널 재연결 중 오류 발생: {e}"), ephemeral=True)
                await player.destroy(notify=False)
                return None
        else:
            player.text_channel = interaction.channel
            logger.debug(f"[{interaction.guild.name}] 기존 플레이어 반환.")
        return player

    logger.info(f"[{interaction.guild.name}] 새 플레이어 생성 시도.")
    channel = await get_voice_channel(interaction)
    if not channel:
        return None

    try:
        voice_client = await channel.connect()

        player = MusicPlayer(interaction.guild, interaction.channel, voice_client, bot)
        bot.music_players[guild_id] = player
        logger.info(f"[{interaction.guild.name}] 새 플레이어 생성 및 음성 채널 연결 성공: {channel.name}")
        return player
    except discord.ClientException as e:
        logger.error(f"[{interaction.guild.name}] 음성 채널 연결 실패 (ClientException): {e}")
        await interaction.followup.send(embed=make_embed(f"⚠️ 음성 채널 연결 실패: 다른 봇이 이미 사용 중일 수 있습니다. 오류: {e}"), ephemeral=True)
        return None
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 플레이어 생성 또는 연결 실패: {e}", exc_info=True)
        await interaction.followup.send(embed=make_embed(f"⚠️ 플레이어 준비 중 오류 발생: {e}"), ephemeral=True)
        return None


async def process_ytdl_data(interaction: discord.Interaction, data, player: MusicPlayer, is_playlist: bool):
    requester_mention = interaction.user.mention

    if data is None:
        await interaction.followup.send(embed=make_embed("❗ 검색 결과가 없거나 처리 중 오류가 발생했습니다."))
        return

    added_count = 0
    playlist_title = "알 수 없는 플레이리스트"

    try:
        if isinstance(data, dict) and is_playlist:
            playlist_title = data.get('title', playlist_title)
            player.current_playlist_url = data.get("original_url")
            player.next_playlist_index = data.get("next_start_index", 1)
            player.playlist_requester = requester_mention

            logger.info(f"[{interaction.guild.name}] Lazy Loading 플레이리스트 처리: '{playlist_title}' (첫 배치), 요청자: {interaction.user.name}")

            initial_entries = data.get("entries", [])
            if not initial_entries:
                 logger.warning(f"[{interaction.guild.name}] 플레이리스트 '{playlist_title}'의 첫 배치에 항목 없음.")
                 await interaction.followup.send(embed=make_embed(f"❗ 플레이리스트 '{playlist_title}'에서 초기 곡 정보를 가져오지 못했습니다."))
                 player.current_playlist_url = None
                 return

            sources_to_add = []
            for entry in initial_entries:
                if not is_valid_entry(entry):
                    logger.warning(f"[{interaction.guild.name}] 플레이리스트 항목 누락된 키: {entry.get('title')}")
                    continue
                try:
                    src = create_ffmpeg_source(entry, requester_mention, FFMPEG_OPTIONS)
                    sources_to_add.append(src)
                    added_count += 1
                except Exception as e:
                    logger.error(f"[{interaction.guild.name}] FFmpegPCMAudio 생성 실패 (플레이리스트): {entry.get('title')}, 오류: {e}")
                    continue

            if not sources_to_add:
                await interaction.followup.send(embed=make_embed(f"❗ 플레이리스트 '{playlist_title}'에서 유효한 초기 곡을 처리하지 못했습니다."))
                player.current_playlist_url = None
                return

            for s in sources_to_add:
                await player.queue.put(s)

            msg = f"✅ 플레이리스트 '**{playlist_title}**'의 첫 {added_count}곡을 추가했습니다. 나머지는 재생 시 자동으로 로드됩니다."
            await interaction.followup.send(embed=make_embed(msg))

        elif isinstance(data, dict) and not is_playlist:
            if not is_valid_entry(data):
                raise ValueError("단일 곡 데이터 누락된 필드")
            source = create_ffmpeg_source(data, requester_mention, FFMPEG_OPTIONS)
            await player.queue.put(source)
            added_count = 1
            logger.info(f"[{interaction.guild.name}] 단일 곡 추가: '{source.title}', 요청자: {interaction.user.name}")
            msg = f"✅ 대기열에 추가됨: [**{source.title}**]({source.webpage_url})"
            await interaction.followup.send(embed=make_embed(msg))

        else:
            logger.error(f"[{interaction.guild.name}] 처리할 수 없는 데이터 형식 수신: {type(data)}")
            await interaction.followup.send(embed=make_embed("❗ 예상치 못한 오류가 발생했습니다. (데이터 형식)"))
            return

    except Exception as e:
        logger.error(f"[{interaction.guild.name}] process_ytdl_data 중 예외 발생: {e}", exc_info=True)
        await interaction.followup.send(embed=make_embed(f"❗ 곡 정보를 처리하는 중 심각한 오류 발생: {e}"))


@bot.event
async def on_ready():
    print(f"--- 봇 정보 ---")
    print(f"봇 이름: {bot.user.name}")
    print(f"봇 ID: {bot.user.id}")
    print(f"Discord.py 버전: {discord.__version__}")
    print(f"실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("---------------")
    logger.info(f"Bot Ready. Logged in as {bot.user.name} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"동기화된 커맨드 {len(synced)}개.")
        logger.info(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"커맨드 동기화 실패: {e}")
        logger.error(f"Failed to sync commands: {e}")

@bot.tree.command(name="재생", description="YouTube에서 노래/플레이리스트를 재생합니다 (URL 또는 검색어).")
@app_commands.describe(query="재생할 노래/플레이리스트의 제목 또는 URL")
async def 재생(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=False, thinking=True)

    is_playlist_url = "list=" in query

    player = await get_player(interaction)
    if player is None:
        logger.warning(f"[{interaction.guild.name}] 플레이어 준비 실패 (get_player 반환 None).")
        return

    loop = bot.loop
    try:
        logger.info(f"[{interaction.guild.name}] YTDL 정보 검색 시작: '{query}'")
        data = await YTDLSource.create_source(query, loop=loop)
    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"[{interaction.guild.name}] YTDL DownloadError for '{query}': {e}")

        if "is not available" in str(e) or "Private video" in str(e):
             msg = "❗ 해당 영상을 찾을 수 없거나 비공개 영상입니다."
        elif "Unsupported URL" in str(e):
             msg = "❗ 지원하지 않는 URL 형식입니다."
        else:
            msg = f"❗ 영상을 가져오는 중 오류 발생: {e}"
        await interaction.followup.send(embed=make_embed(msg))
        return
    except IndexError:
        logger.warning(f"[{interaction.guild.name}] 검색 결과 없음 추정: '{query}'")
        await interaction.followup.send(embed=make_embed("❗ 검색 결과가 없습니다."))
        return
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] YTDLSource.create_source 예외: '{query}', 오류: {e}", exc_info=True)
        await interaction.followup.send(embed=make_embed(f"❗ 음악 정보를 가져오는 중 오류 발생: {e}"))
        return

    await process_ytdl_data(interaction, data, player, is_playlist_url)


@bot.tree.command(name="대기열", description="현재 재생 대기열을 확인합니다.")
async def 대기열(interaction: discord.Interaction):
    player = bot.music_players.get(interaction.guild.id)

    if player is None or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    queue_items = player.get_queue_items()
    embed = discord.Embed(title="🎶 음악 대기열", color=discord.Color.purple())

    current_msg = "없음"
    if player.current:
        current_duration_str = f" ({format_time(player.current.duration)})" if getattr(player.current, 'duration', None) else ""
        current_msg = f"[**{player.current.title}**]({getattr(player.current, 'webpage_url', '')}){current_duration_str} - {player.current.requester}"
    embed.add_field(name="🎵 현재 재생 중", value=current_msg, inline=False)

    if not queue_items:
        queue_list_str = "📭 대기열이 비어있습니다."
        queue_count = 0
    else:
        queue_list_str = ""
        display_count = min(len(queue_items), 10)
        for i, song in enumerate(queue_items[:display_count], 1):
            duration_str = f" ({format_time(song.duration)})" if getattr(song, 'duration', None) else ""
            queue_list_str += f"{i}. [**{song.title}**]({getattr(song, 'webpage_url', '')}){duration_str} - {song.requester}\n"

        if len(queue_items) > display_count:
            queue_list_str += f"\n... 외 {len(queue_items) - display_count}곡 더 있음"
        queue_count = len(queue_items)

    embed.add_field(name=f"⏭️ 다음 곡 ({queue_count}개)", value=queue_list_str, inline=False)

    if player.current_playlist_url:
        embed.set_footer(text=f"플레이리스트 자동 로딩 중... (다음 로드 시작: {player.next_playlist_index}번째 곡)")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
@app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
async def 삭제(interaction: discord.Interaction, position: app_commands.Range[int, 1]):
    player = bot.music_players.get(interaction.guild.id)
    if player is None or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    queue_list = player.get_queue_items()

    if not queue_list:
        await interaction.followup.send(embed=make_embed("📭 대기열이 비어있습니다."))
        return
    if position > len(queue_list):
        await interaction.followup.send(embed=make_embed(f"❗ 유효하지 않은 순번입니다. (최대 {len(queue_list)})"))
        return

    try:
        removed_song = queue_list.pop(position - 1)

        while not player.queue.empty():
            try: player.queue.get_nowait()
            except asyncio.QueueEmpty: break

        for song in queue_list:
            await player.queue.put(song)

        logger.info(f"[{interaction.guild.name}] 대기열에서 곡 제거: {position}. {removed_song.title}, 요청자: {interaction.user.name}")
        await interaction.followup.send(embed=make_embed(f"🗑️ 제거됨 (#{position}): **{removed_song.title}**"))
    except IndexError:
        await interaction.followup.send(embed=make_embed("❗ 곡을 제거하는 중 오류가 발생했습니다. (인덱스 오류)"))
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 대기열 삭제 중 오류: {e}", exc_info=True)
        await interaction.followup.send(embed=make_embed(f"❗ 곡 제거 중 오류 발생: {e}"))


@bot.tree.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
async def 스킵(interaction: discord.Interaction):
    player = bot.music_players.get(interaction.guild.id)
    if player is None or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."), ephemeral=True)
        return

    if player.voice_client.is_playing():
        skipped_title = getattr(player.current, 'title', '현재 곡')
        logger.info(f"[{interaction.guild.name}] 곡 스킵: '{skipped_title}', 요청자: {interaction.user.name}")
        player.voice_client.stop()
        await interaction.response.send_message(embed=make_embed(f"⏭️ '**{skipped_title}**'을(를) 건너뛰었습니다."))
    else:
        await interaction.response.send_message(embed=make_embed("🚫 재생 중인 곡이 없습니다."), ephemeral=True)


@bot.tree.command(name="정지", description="음악 재생을 중지하고 봇을 음성 채널에서 내보냅니다.")
async def 정지(interaction: discord.Interaction):
    player = bot.music_players.get(interaction.guild.id)
    if player is None or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."), ephemeral=True)
        return

    logger.info(f"[{interaction.guild.name}] 정지 명령어 실행됨. 플레이어 파괴 시도. 요청자: {interaction.user.name}")
    await player.destroy(notify=False)

    await interaction.response.send_message(embed=make_embed("⏹️ 음악 재생을 중지하고 음성 채널 연결을 종료했습니다."))


@bot.tree.command(name="현재곡", description="현재 재생 중인 곡 정보를 표시합니다.")
async def 현재곡(interaction: discord.Interaction):
    player = bot.music_players.get(interaction.guild.id)
    if player is None or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."), ephemeral=True)
        return

    if player.current is None:
        await interaction.response.send_message(embed=make_embed("🚫 현재 재생 중인 곡이 없습니다."), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    embed = player.build_now_playing_embed()

    playback_time = player.get_playback_time()
    if player.current.duration and playback_time is not None:
        progress = int((playback_time / player.current.duration) * 20)
        bar = '▬' * progress + '🔘' + '▬' * (20 - progress -1)
        embed.add_field(name="진행률", value=f"`{format_time(playback_time)} / {format_time(player.current.duration)}`\n`{bar}`", inline=False)

    await interaction.followup.send(embed=embed)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.id == bot.user.id:
        if before.channel and not after.channel:
            guild_id = member.guild.id
            if guild_id in bot.music_players:
                player = bot.music_players[guild_id]
                logger.info(f"[{member.guild.name}] 봇 음성 연결 해제 감지 (채널: {before.channel.name}). 플레이어 정리.")
                await player.destroy(notify=False)
        return

    if before.channel:
        guild_id = member.guild.id
        if guild_id in bot.music_players:
            player = bot.music_players[guild_id]
            vc = player.voice_client
            if vc and vc.channel == before.channel:
                real_members = [m for m in before.channel.members if not m.bot]
                if not real_members:
                    logger.info(f"[{member.guild.name}] 유저({member.name}) 퇴장/이동으로 채널({before.channel.name})에 봇만 남음. player_loop의 유휴 타이머에 의해 처리될 예정.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    error_message = f"명령어 처리 중 오류가 발생했습니다: {error}"
    log_message = f"AppCommandError in guild {interaction.guild_id} (cmd: {interaction.command.name if interaction.command else 'Unknown'}): {error}"

    if isinstance(error, app_commands.CommandNotFound):
        error_message = "알 수 없는 명령어입니다."
    elif isinstance(error, app_commands.CheckFailure):
        error_message = "이 명령어를 실행할 권한이 없습니다."
    elif isinstance(error, app_commands.MissingRequiredArgument):
        error_message = f"필수 입력 항목 `{error.param.name}`(이)가 누락되었습니다."
    elif isinstance(error, app_commands.CommandOnCooldown):
        error_message = f"명령어를 너무 자주 사용하고 있습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요."
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        error_message = f"봇이 명령 실행에 필요한 권한({perms})을 가지고 있지 않습니다."
        log_message += f" Missing Perms: {perms}"
    elif isinstance(error, app_commands.NoPrivateMessage):
         error_message = "이 명령어는 개인 메시지(DM)에서는 사용할 수 없습니다."

    logger.error(log_message, exc_info=True)
    embed = make_embed(f"❗ {error_message}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.NotFound:
         logger.warning(f"[{interaction.guild_id}] 오류 메시지 전송 실패: 상호작용을 찾을 수 없음.")
    except Exception as e:
        logger.error(f"[{interaction.guild_id}] 오류 메시지 전송 중 예외 발생: {e}", exc_info=True)

from datetime import datetime

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("오류: BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
        logger.critical("BOT_TOKEN environment variable is not set. Bot cannot start.")
    else:
        try:
             bot.run(BOT_TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.critical("Failed to log in. Check your BOT_TOKEN.")
        except Exception as e:
             logger.critical(f"An error occurred while running the bot: {e}", exc_info=True)