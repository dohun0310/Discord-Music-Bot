"""
Discord 음악 봇 메인 모듈

봇의 진입점이며, 슬래시 명령어와 이벤트 핸들러를 정의합니다.
YouTube에서 음악을 검색하고 재생하는 기능을 제공합니다.
"""

import logging
from datetime import datetime
from typing import Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from config import (
    BOT_TOKEN,
    Colors,
    Emoji,
    FFMPEG_OPTIONS,
    MAX_QUEUE_DISPLAY,
)
from music_player import MusicPlayer, RepeatMode
from utils import (
    create_ffmpeg_source,
    create_progress_bar,
    format_time,
    is_valid_entry,
    make_embed,
    make_error_embed,
    make_success_embed,
    make_warning_embed,
    truncate_string,
)
from ytdl_source import YTDLSource

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s:%(lineno)d] %(message)s'
)
logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)

logger = logging.getLogger('discord.bot.main')

# 봇 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

# 봇 인스턴스 생성
bot = commands.Bot(command_prefix="!", intents=intents)
bot.music_players = {}


async def get_voice_channel(interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    """
    사용자가 현재 접속해 있는 음성 채널을 가져옵니다.

    Args:
        interaction: Discord 상호작용 객체

    Returns:
        사용자의 음성 채널, 접속해있지 않으면 None
    """
    logger.debug(
        f"[{interaction.guild.name}] 음성 채널 확인 - "
        f"사용자: {interaction.user.name}"
    )

    if not interaction.user.voice or not interaction.user.voice.channel:
        logger.debug(
            f"[{interaction.guild.name}] 사용자 {interaction.user.name}이(가) "
            "음성 채널에 접속해 있지 않음"
        )
        await interaction.response.send_message(
            embed=make_warning_embed("먼저 음성 채널에 접속해주세요."),
            ephemeral=True
        )
        return None

    channel = interaction.user.voice.channel
    logger.debug(
        f"[{interaction.guild.name}] 사용자 음성 채널 확인됨 - "
        f"채널: {channel.name}"
    )
    return channel


async def get_player(interaction: discord.Interaction) -> Optional[MusicPlayer]:
    """
    서버의 음악 플레이어를 가져오거나 새로 생성합니다.
    """
    guild_id = interaction.guild.id
    logger.debug(f"[{interaction.guild.name}] 플레이어 조회 - 서버 ID: {guild_id}")

    player = bot.music_players.get(guild_id)

    if player:
        logger.debug(
            f"[{interaction.guild.name}] 기존 플레이어 발견 - "
            f"연결됨: {player.voice_client.is_connected() if player.voice_client else False}"
        )

        if not player.voice_client or not player.voice_client.is_connected():
            logger.warning(f"[{interaction.guild.name}] 기존 플레이어 연결 끊김 - 재연결 시도")

            channel = await get_voice_channel(interaction)
            if not channel:
                await interaction.followup.send(
                    embed=make_error_embed("플레이어 재연결 실패: 음성 채널에 접속해주세요."),
                    ephemeral=True
                )
                await player.destroy(notify=False)
                return None

            try:
                if player.voice_client:
                    await player.voice_client.disconnect(force=True)
                player.voice_client = await channel.connect()
                player.text_channel = interaction.channel
                logger.info(f"[{interaction.guild.name}] 음성 채널 재연결 성공 - 채널: {channel.name}")
            except Exception as e:
                logger.error(f"[{interaction.guild.name}] 음성 채널 재연결 실패 - {e}", exc_info=True)
                await interaction.followup.send(
                    embed=make_error_embed(f"재연결 중 오류 발생: {e}"),
                    ephemeral=True
                )
                await player.destroy(notify=False)
                return None
        else:
            player.text_channel = interaction.channel

        return player

    # 새 플레이어 생성
    logger.info(f"[{interaction.guild.name}] 새 플레이어 생성 시도")

    channel = await get_voice_channel(interaction)
    if not channel:
        return None

    try:
        voice_client = await channel.connect()
        player = MusicPlayer(interaction.guild, interaction.channel, voice_client, bot)
        bot.music_players[guild_id] = player
        logger.info(f"[{interaction.guild.name}] 새 플레이어 생성 완료 - 음성 채널: {channel.name}")
        return player

    except discord.ClientException as e:
        logger.error(f"[{interaction.guild.name}] 음성 채널 연결 실패 (ClientException) - {e}")
        await interaction.followup.send(
            embed=make_error_embed(f"음성 채널 연결 실패: {e}"),
            ephemeral=True
        )
        return None

    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 플레이어 생성 실패 - {e}", exc_info=True)
        await interaction.followup.send(
            embed=make_error_embed(f"플레이어 준비 중 오류 발생: {e}"),
            ephemeral=True
        )
        return None


async def process_ytdl_data(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    is_playlist: bool
) -> None:
    """yt-dlp에서 받은 데이터를 처리하여 대기열에 추가합니다."""
    requester = interaction.user.mention

    if data is None:
        await interaction.followup.send(
            embed=make_error_embed("검색 결과가 없거나 처리 중 오류가 발생했습니다.")
        )
        return

    try:
        if is_playlist and isinstance(data, dict):
            await _process_playlist(interaction, data, player, requester)
        elif isinstance(data, dict):
            await _process_single_track(interaction, data, player, requester)
        else:
            logger.error(f"[{interaction.guild.name}] 예상치 못한 데이터 형식 - 타입: {type(data)}")
            await interaction.followup.send(
                embed=make_error_embed("예상치 못한 오류가 발생했습니다.")
            )
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 데이터 처리 중 오류 - {e}", exc_info=True)
        await interaction.followup.send(
            embed=make_error_embed(f"곡 정보 처리 중 오류 발생: {e}")
        )


async def _process_playlist(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    requester: str
) -> None:
    """플레이리스트 데이터를 처리하여 대기열에 추가합니다."""
    playlist_title = data.get('title', '알 수 없는 플레이리스트')
    player.current_playlist_url = data.get("original_url")
    player.next_playlist_index = data.get("next_start_index", 1)
    player.playlist_requester = requester

    logger.info(f"[{interaction.guild.name}] 플레이리스트 처리 시작 - 제목: '{playlist_title}'")

    entries = data.get("entries", [])
    if not entries:
        await interaction.followup.send(
            embed=make_warning_embed(f"플레이리스트 '{playlist_title}'에서 곡을 찾지 못했습니다.")
        )
        player.current_playlist_url = None
        return

    added = 0
    for entry in entries:
        if not is_valid_entry(entry):
            continue
        try:
            source = create_ffmpeg_source(entry, requester, FFMPEG_OPTIONS)
            await player.queue.put(source)
            added += 1
        except Exception as e:
            logger.error(f"[{interaction.guild.name}] FFmpeg 소스 생성 실패 - {e}")

    if not added:
        await interaction.followup.send(
            embed=make_warning_embed(f"플레이리스트 '{playlist_title}'에서 유효한 곡을 찾지 못했습니다.")
        )
        player.current_playlist_url = None
        return

    embed = discord.Embed(
        title=f"{Emoji.PLAYLIST} 플레이리스트 추가됨",
        description=f"**{truncate_string(playlist_title, 50)}**\n\n"
                    f"{Emoji.MUSIC} `{added}곡` 추가됨\n"
                    f"{Emoji.USER} {requester}",
        color=Colors.SUCCESS
    )
    embed.set_footer(text="나머지 곡은 재생 시 자동으로 로드됩니다")

    await interaction.followup.send(embed=embed)


async def _process_single_track(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    requester: str
) -> None:
    """단일 곡 데이터를 처리하여 대기열에 추가합니다."""
    if not is_valid_entry(data):
        raise ValueError("필수 곡 정보가 누락되었습니다")

    source = create_ffmpeg_source(data, requester, FFMPEG_OPTIONS)
    await player.queue.put(source)

    logger.info(f"[{interaction.guild.name}] 단일 곡 추가 완료 - 제목: '{source.title}'")

    embed = discord.Embed(
        title=f"{Emoji.SUCCESS} 대기열에 추가됨",
        description=f"**[{truncate_string(source.title, 50)}]({source.webpage_url})**",
        color=Colors.SUCCESS
    )

    if source.duration:
        embed.add_field(name="길이", value=f"`{format_time(source.duration)}`", inline=True)

    embed.add_field(name="요청자", value=requester, inline=True)

    queue_pos = player.queue.qsize()
    embed.add_field(name="대기열 위치", value=f"`#{queue_pos}`", inline=True)

    if source.thumbnail:
        embed.set_thumbnail(url=source.thumbnail)

    await interaction.followup.send(embed=embed)


# ============== 이벤트 핸들러 ==============

@bot.event
async def on_ready():
    """봇이 준비되었을 때 호출됩니다."""
    print(f"""
╔══════════════════════════════════════╗
║       🎵 Discord Music Bot 🎵        ║
╠══════════════════════════════════════╣
║  봇 이름: {bot.user.name:<25} ║
║  봇 ID: {bot.user.id:<27} ║
║  Discord.py: {discord.__version__:<22} ║
║  시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<18} ║
╚══════════════════════════════════════╝
    """)

    logger.info(f"봇 준비 완료 - {bot.user.name} ({bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"  ✓ 동기화된 명령어: {len(synced)}개")
        logger.info(f"슬래시 명령어 동기화 완료 - {len(synced)}개")
    except Exception as e:
        print(f"  ✗ 명령어 동기화 실패: {e}")
        logger.error(f"슬래시 명령어 동기화 실패 - {e}")


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    """음성 상태 변경 이벤트 핸들러입니다."""
    if member.id == bot.user.id and before.channel and not after.channel:
        guild_id = member.guild.id
        if guild_id in bot.music_players:
            player = bot.music_players[guild_id]
            logger.info(f"[{member.guild.name}] 봇 음성 연결 해제 감지 - 플레이어 정리")
            await player.destroy(notify=False)


# ============== 슬래시 명령어 ==============

@bot.tree.command(name="재생", description="YouTube에서 노래/플레이리스트를 재생합니다.")
@app_commands.describe(query="재생할 노래/플레이리스트의 제목 또는 URL")
async def play(interaction: discord.Interaction, query: str):
    """재생 명령어 - YouTube에서 음악을 검색하고 재생합니다."""
    logger.info(f"[{interaction.guild.name}] /재생 - 사용자: {interaction.user.name}, 쿼리: '{query}'")
    await interaction.response.defer(thinking=True)

    player = await get_player(interaction)
    if player is None:
        return

    try:
        data = await YTDLSource.create_source(query, loop=bot.loop)
    except yt_dlp.utils.DownloadError as e:
        error_str = str(e)
        if "is not available" in error_str or "Private video" in error_str:
            msg = "해당 영상을 찾을 수 없거나 비공개 영상입니다."
        elif "Unsupported URL" in error_str:
            msg = "지원하지 않는 URL 형식입니다."
        else:
            msg = f"영상을 가져오는 중 오류 발생: {e}"
        await interaction.followup.send(embed=make_error_embed(msg))
        return
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] YouTube 정보 검색 실패 - {e}", exc_info=True)
        await interaction.followup.send(embed=make_error_embed(f"음악 정보를 가져오는 중 오류 발생: {e}"))
        return

    is_playlist = isinstance(data, dict) and data.get("type") == "playlist"
    await process_ytdl_data(interaction, data, player, is_playlist)


@bot.tree.command(name="대기열", description="현재 재생 대기열을 확인합니다.")
async def queue(interaction: discord.Interaction):
    """대기열 명령어 - 현재 재생 대기열을 표시합니다."""
    logger.info(f"[{interaction.guild.name}] /대기열 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()

    queue_items = player.get_queue_items()

    embed = discord.Embed(
        title=f"{Emoji.QUEUE} 음악 대기열",
        color=Colors.QUEUE
    )

    # 현재 재생 중인 곡
    if player.current:
        duration = getattr(player.current, 'duration', None)
        playback_time = player.get_playback_time()

        current_info = f"**[{truncate_string(player.current.title, 40)}]({getattr(player.current, 'webpage_url', '')})**\n"

        if duration and playback_time:
            progress_bar = create_progress_bar(playback_time, duration, 10)
            current_info += f"`{format_time(playback_time)}` {progress_bar} `{format_time(duration)}`\n"

        current_info += f"{Emoji.USER} {player.current.requester}"

        # 상태 아이콘
        status_icon = Emoji.PAUSE if player.paused else Emoji.PLAY
        embed.add_field(name=f"{status_icon} 현재 재생 중", value=current_info, inline=False)
    else:
        embed.add_field(name=f"{Emoji.MUSIC} 현재 재생 중", value="없음", inline=False)

    # 대기열
    if not queue_items:
        queue_str = f"{Emoji.EMPTY} 대기열이 비어있습니다."
    else:
        lines = []
        for i, song in enumerate(queue_items[:MAX_QUEUE_DISPLAY], 1):
            duration = getattr(song, 'duration', None)
            duration_str = f" `{format_time(duration)}`" if duration else ""
            lines.append(f"`{i}.` **{truncate_string(song.title, 35)}**{duration_str}")

        if len(queue_items) > MAX_QUEUE_DISPLAY:
            lines.append(f"\n*... 외 {len(queue_items) - MAX_QUEUE_DISPLAY}곡*")
        queue_str = "\n".join(lines)

    embed.add_field(name=f"{Emoji.PLAYLIST} 다음 곡 ({len(queue_items)}개)", value=queue_str, inline=False)

    # 재생 설정 상태
    status_parts = []
    status_parts.append(f"{Emoji.VOLUME_HIGH} `{player.volume:.0%}`")

    if player.repeat_mode == RepeatMode.ONE:
        status_parts.append(f"{Emoji.REPEAT_ONE} 한곡 반복")
    elif player.repeat_mode == RepeatMode.ALL:
        status_parts.append(f"{Emoji.REPEAT} 전체 반복")

    if player.shuffle:
        status_parts.append(f"{Emoji.SHUFFLE} 셔플")

    embed.set_footer(text=" │ ".join(status_parts))

    if player.current and getattr(player.current, 'thumbnail', None):
        embed.set_thumbnail(url=player.current.thumbnail)

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="현재곡", description="현재 재생 중인 곡 정보를 표시합니다.")
async def now_playing(interaction: discord.Interaction):
    """현재곡 명령어 - 현재 재생 중인 곡의 정보와 진행률을 표시합니다."""
    logger.info(f"[{interaction.guild.name}] /현재곡 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    if not player.current:
        await interaction.response.send_message(
            embed=make_warning_embed("현재 재생 중인 곡이 없습니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()
    embed = player.build_progress_embed()
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
async def skip(interaction: discord.Interaction):
    """스킵 명령어 - 현재 재생 중인 곡을 건너뜁니다."""
    logger.info(f"[{interaction.guild.name}] /스킵 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    if player.voice_client.is_playing() or player.voice_client.is_paused():
        title = getattr(player.current, 'title', '현재 곡')
        player.voice_client.stop()

        # 한 곡 반복 모드였다면 해제
        if player.repeat_mode == RepeatMode.ONE:
            player.repeat_mode = RepeatMode.OFF

        await interaction.response.send_message(
            embed=make_success_embed(f"**{truncate_string(title, 40)}** 건너뛰었습니다.")
        )
    else:
        await interaction.response.send_message(
            embed=make_warning_embed("재생 중인 곡이 없습니다."),
            ephemeral=True
        )


@bot.tree.command(name="정지", description="음악 재생을 중지하고 봇을 퇴장시킵니다.")
async def stop(interaction: discord.Interaction):
    """정지 명령어 - 음악 재생을 중지하고 음성 채널에서 나갑니다."""
    logger.info(f"[{interaction.guild.name}] /정지 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    await player.destroy(notify=False)
    await interaction.response.send_message(
        embed=make_embed(
            f"{Emoji.STOP} 음악 재생을 중지하고 연결을 종료했습니다.",
            Colors.INFO
        )
    )


@bot.tree.command(name="일시정지", description="음악 재생을 일시정지합니다.")
async def pause(interaction: discord.Interaction):
    """일시정지 명령어"""
    logger.info(f"[{interaction.guild.name}] /일시정지 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    if await player.pause():
        await interaction.response.send_message(
            embed=make_embed(f"{Emoji.PAUSE} 일시정지되었습니다.", Colors.INFO)
        )
    else:
        await interaction.response.send_message(
            embed=make_warning_embed("재생 중인 곡이 없습니다."),
            ephemeral=True
        )


@bot.tree.command(name="재개", description="일시정지된 음악을 다시 재생합니다.")
async def resume(interaction: discord.Interaction):
    """재개 명령어"""
    logger.info(f"[{interaction.guild.name}] /재개 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    if await player.resume():
        await interaction.response.send_message(
            embed=make_embed(f"{Emoji.PLAY} 재생을 재개합니다.", Colors.SUCCESS)
        )
    else:
        await interaction.response.send_message(
            embed=make_warning_embed("일시정지된 곡이 없습니다."),
            ephemeral=True
        )


@bot.tree.command(name="볼륨", description="볼륨을 조절합니다. (0-200%)")
@app_commands.describe(volume="볼륨 (0-200)")
async def volume(interaction: discord.Interaction, volume: app_commands.Range[int, 0, 200]):
    """볼륨 명령어"""
    logger.info(f"[{interaction.guild.name}] /볼륨 {volume} - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    new_volume = player.set_volume(volume / 100)

    # 볼륨 레벨에 따른 이모지
    if new_volume == 0:
        emoji = Emoji.VOLUME_MUTE
    elif new_volume < 0.5:
        emoji = Emoji.VOLUME_LOW
    else:
        emoji = Emoji.VOLUME_HIGH

    await interaction.response.send_message(
        embed=make_embed(f"{emoji} 볼륨: **{new_volume:.0%}**", Colors.INFO)
    )


@bot.tree.command(name="반복", description="반복 재생 모드를 변경합니다.")
async def repeat(interaction: discord.Interaction):
    """반복 명령어"""
    logger.info(f"[{interaction.guild.name}] /반복 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    mode = player.toggle_repeat()

    if mode == RepeatMode.OFF:
        msg = f"{Emoji.REPEAT} 반복 재생이 **꺼졌습니다**"
    elif mode == RepeatMode.ALL:
        msg = f"{Emoji.REPEAT} **전체 반복** 모드가 켜졌습니다"
    else:
        msg = f"{Emoji.REPEAT_ONE} **한 곡 반복** 모드가 켜졌습니다"

    await interaction.response.send_message(embed=make_embed(msg, Colors.INFO))


@bot.tree.command(name="셔플", description="대기열을 섞습니다.")
async def shuffle(interaction: discord.Interaction):
    """셔플 명령어"""
    logger.info(f"[{interaction.guild.name}] /셔플 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    count = player.shuffle_queue()
    if count > 0:
        await interaction.response.send_message(
            embed=make_success_embed(f"대기열의 **{count}곡**을 섞었습니다.")
        )
    else:
        await interaction.response.send_message(
            embed=make_warning_embed("대기열에 곡이 부족합니다."),
            ephemeral=True
        )


@bot.tree.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
@app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
async def remove(interaction: discord.Interaction, position: app_commands.Range[int, 1]):
    """삭제 명령어"""
    logger.info(f"[{interaction.guild.name}] /삭제 {position} - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client or not player.voice_client.is_connected():
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()

    queue_list = player.get_queue_items()
    if not queue_list:
        await interaction.followup.send(embed=make_warning_embed("대기열이 비어있습니다."))
        return

    if position > len(queue_list):
        await interaction.followup.send(
            embed=make_warning_embed(f"유효하지 않은 순번입니다. (최대: {len(queue_list)})")
        )
        return

    try:
        removed = queue_list.pop(position - 1)

        while not player.queue.empty():
            try:
                player.queue.get_nowait()
            except Exception:
                break

        for song in queue_list:
            await player.queue.put(song)

        await interaction.followup.send(
            embed=make_success_embed(f"**{truncate_string(removed.title, 40)}** 제거되었습니다.")
        )
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 곡 삭제 실패 - {e}", exc_info=True)
        await interaction.followup.send(embed=make_error_embed(f"곡 제거 중 오류 발생: {e}"))


@bot.tree.command(name="비우기", description="대기열을 비웁니다.")
async def clear(interaction: discord.Interaction):
    """비우기 명령어"""
    logger.info(f"[{interaction.guild.name}] /비우기 - 사용자: {interaction.user.name}")

    player = bot.music_players.get(interaction.guild.id)
    if not player or not player.voice_client:
        await interaction.response.send_message(
            embed=make_warning_embed("봇이 음성 채널에 없습니다."),
            ephemeral=True
        )
        return

    count = player.clear_queue()
    if count > 0:
        await interaction.response.send_message(
            embed=make_success_embed(f"대기열에서 **{count}곡**을 제거했습니다.")
        )
    else:
        await interaction.response.send_message(
            embed=make_warning_embed("대기열이 이미 비어있습니다."),
            ephemeral=True
        )


# ============== 에러 핸들러 ==============

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    """슬래시 명령어 오류 핸들러입니다."""
    cmd_name = interaction.command.name if interaction.command else "알 수 없음"
    logger.error(f"[{interaction.guild.name}] 명령어 오류 - {cmd_name}: {error}", exc_info=True)

    if isinstance(error, app_commands.CommandNotFound):
        msg = "알 수 없는 명령어입니다."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "이 명령어를 실행할 권한이 없습니다."
    elif isinstance(error, app_commands.MissingRequiredArgument):
        msg = f"필수 입력 항목 `{error.param.name}`(이)가 누락되었습니다."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"명령어를 너무 자주 사용하고 있습니다. {error.retry_after:.1f}초 후에 다시 시도해주세요."
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        msg = f"봇에게 필요한 권한이 없습니다: {perms}"
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "이 명령어는 DM에서 사용할 수 없습니다."
    else:
        msg = f"명령어 처리 중 오류가 발생했습니다."

    embed = make_error_embed(msg)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.NotFound:
        logger.warning(f"[{interaction.guild.name}] 오류 메시지 전송 실패 - 상호작용 없음")
    except Exception as e:
        logger.error(f"[{interaction.guild.name}] 오류 메시지 전송 중 예외 - {e}")


# ============== 메인 ==============

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("\n  ✗ 오류: BOT_TOKEN 환경 변수가 설정되지 않았습니다.\n")
        logger.critical("BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
    else:
        logger.info("봇 시작 중...")
        try:
            bot.run(BOT_TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.critical("로그인 실패. BOT_TOKEN을 확인해주세요.")
        except Exception as e:
            logger.critical(f"봇 실행 중 오류 발생 - {e}", exc_info=True)
