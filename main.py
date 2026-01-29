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

from config import BOT_TOKEN, FFMPEG_OPTIONS, MAX_QUEUE_DISPLAY
from music_player import MusicPlayer
from utils import create_ffmpeg_source, format_time, is_valid_entry, make_embed
from ytdl_source import YTDLSource

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,  # 상세한 로깅을 위해 DEBUG 레벨 사용
    format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s:%(lineno)d] %(message)s'
)
# Discord 라이브러리의 과도한 로깅 억제
logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)

logger = logging.getLogger('discord.bot.main')

# 봇 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True  # 메시지 내용 읽기 권한
intents.guilds = True  # 서버 정보 접근 권한
intents.voice_states = True  # 음성 상태 변경 감지 권한

# 봇 인스턴스 생성
bot = commands.Bot(command_prefix="!", intents=intents)
bot.music_players = {}  # 서버별 플레이어 저장 딕셔너리


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
            embed=make_embed("🚫 먼저 음성 채널에 접속해주세요."),
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

    기존 플레이어가 있지만 연결이 끊긴 경우 재연결을 시도합니다.

    Args:
        interaction: Discord 상호작용 객체

    Returns:
        MusicPlayer 인스턴스, 실패 시 None
    """
    guild_id = interaction.guild.id
    logger.debug(
        f"[{interaction.guild.name}] 플레이어 조회 - "
        f"서버 ID: {guild_id}"
    )

    player = bot.music_players.get(guild_id)

    # 기존 플레이어가 있는 경우
    if player:
        logger.debug(
            f"[{interaction.guild.name}] 기존 플레이어 발견 - "
            f"음성 클라이언트: {player.voice_client is not None}, "
            f"연결됨: {player.voice_client.is_connected() if player.voice_client else False}"
        )

        # 연결이 끊긴 경우 재연결 시도
        if not player.voice_client or not player.voice_client.is_connected():
            logger.warning(
                f"[{interaction.guild.name}] 기존 플레이어의 음성 연결이 끊김 - "
                "재연결 시도"
            )

            channel = await get_voice_channel(interaction)
            if not channel:
                await interaction.followup.send(
                    embed=make_embed("⚠️ 플레이어 재연결 실패: 음성 채널에 접속해주세요."),
                    ephemeral=True
                )
                await player.destroy(notify=False)
                return None

            try:
                if player.voice_client:
                    await player.voice_client.disconnect(force=True)
                player.voice_client = await channel.connect()
                player.text_channel = interaction.channel
                logger.info(
                    f"[{interaction.guild.name}] 음성 채널 재연결 성공 - "
                    f"채널: {channel.name}"
                )
            except Exception as e:
                logger.error(
                    f"[{interaction.guild.name}] 음성 채널 재연결 실패 - {e}",
                    exc_info=True
                )
                await interaction.followup.send(
                    embed=make_embed(f"⚠️ 재연결 중 오류 발생: {e}"),
                    ephemeral=True
                )
                await player.destroy(notify=False)
                return None
        else:
            player.text_channel = interaction.channel
            logger.debug(f"[{interaction.guild.name}] 기존 플레이어 반환")

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
        logger.info(
            f"[{interaction.guild.name}] 새 플레이어 생성 완료 - "
            f"음성 채널: {channel.name}"
        )
        return player

    except discord.ClientException as e:
        logger.error(
            f"[{interaction.guild.name}] 음성 채널 연결 실패 (ClientException) - {e}"
        )
        await interaction.followup.send(
            embed=make_embed(f"⚠️ 음성 채널 연결 실패: {e}"),
            ephemeral=True
        )
        return None

    except Exception as e:
        logger.error(
            f"[{interaction.guild.name}] 플레이어 생성 실패 - {e}",
            exc_info=True
        )
        await interaction.followup.send(
            embed=make_embed(f"⚠️ 플레이어 준비 중 오류 발생: {e}"),
            ephemeral=True
        )
        return None


async def process_ytdl_data(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    is_playlist: bool
) -> None:
    """
    yt-dlp에서 받은 데이터를 처리하여 대기열에 추가합니다.

    Args:
        interaction: Discord 상호작용 객체
        data: yt-dlp 결과 데이터
        player: 음악 플레이어 인스턴스
        is_playlist: 플레이리스트 여부
    """
    requester = interaction.user.mention
    logger.debug(
        f"[{interaction.guild.name}] YTDL 데이터 처리 시작 - "
        f"플레이리스트: {is_playlist}, 요청자: {interaction.user.name}"
    )

    if data is None:
        logger.warning(f"[{interaction.guild.name}] YTDL 데이터가 None")
        await interaction.followup.send(
            embed=make_embed("❗ 검색 결과가 없거나 처리 중 오류가 발생했습니다.")
        )
        return

    try:
        if is_playlist and isinstance(data, dict):
            await _process_playlist(interaction, data, player, requester)
        elif isinstance(data, dict):
            await _process_single_track(interaction, data, player, requester)
        else:
            logger.error(
                f"[{interaction.guild.name}] 예상치 못한 데이터 형식 - "
                f"타입: {type(data)}"
            )
            await interaction.followup.send(
                embed=make_embed("❗ 예상치 못한 오류가 발생했습니다.")
            )
    except Exception as e:
        logger.error(
            f"[{interaction.guild.name}] 데이터 처리 중 오류 - {e}",
            exc_info=True
        )
        await interaction.followup.send(
            embed=make_embed(f"❗ 곡 정보 처리 중 오류 발생: {e}")
        )


async def _process_playlist(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    requester: str
) -> None:
    """
    플레이리스트 데이터를 처리하여 대기열에 추가합니다.

    Args:
        interaction: Discord 상호작용 객체
        data: 플레이리스트 데이터
        player: 음악 플레이어 인스턴스
        requester: 요청자 멘션
    """
    playlist_title = data.get('title', '알 수 없는 플레이리스트')
    player.current_playlist_url = data.get("original_url")
    player.next_playlist_index = data.get("next_start_index", 1)
    player.playlist_requester = requester

    logger.info(
        f"[{interaction.guild.name}] 플레이리스트 처리 시작 - "
        f"제목: '{playlist_title}', 요청자: {interaction.user.name}"
    )

    entries = data.get("entries", [])
    if not entries:
        logger.warning(
            f"[{interaction.guild.name}] 플레이리스트에 항목 없음 - "
            f"제목: '{playlist_title}'"
        )
        await interaction.followup.send(
            embed=make_embed(f"❗ 플레이리스트 '{playlist_title}'에서 곡을 찾지 못했습니다.")
        )
        player.current_playlist_url = None
        return

    # 각 항목을 대기열에 추가
    added = 0
    for entry in entries:
        if not is_valid_entry(entry):
            logger.debug(
                f"[{interaction.guild.name}] 유효하지 않은 항목 스킵 - "
                f"제목: {entry.get('title', '알 수 없음')}"
            )
            continue
        try:
            source = create_ffmpeg_source(entry, requester, FFMPEG_OPTIONS)
            await player.queue.put(source)
            added += 1
            logger.debug(
                f"[{interaction.guild.name}] 대기열에 곡 추가 - "
                f"제목: '{source.title}'"
            )
        except Exception as e:
            logger.error(
                f"[{interaction.guild.name}] FFmpeg 소스 생성 실패 - "
                f"제목: {entry.get('title', '알 수 없음')}, 오류: {e}"
            )

    if not added:
        logger.warning(
            f"[{interaction.guild.name}] 플레이리스트에서 유효한 곡 없음 - "
            f"제목: '{playlist_title}'"
        )
        await interaction.followup.send(
            embed=make_embed(f"❗ 플레이리스트 '{playlist_title}'에서 유효한 곡을 찾지 못했습니다.")
        )
        player.current_playlist_url = None
        return

    logger.info(
        f"[{interaction.guild.name}] 플레이리스트 처리 완료 - "
        f"제목: '{playlist_title}', 추가된 곡: {added}개"
    )
    await interaction.followup.send(
        embed=make_embed(
            f"✅ 플레이리스트 '**{playlist_title}**'에서 {added}곡을 추가했습니다. "
            "나머지는 재생 시 자동으로 로드됩니다."
        )
    )


async def _process_single_track(
    interaction: discord.Interaction,
    data: dict,
    player: MusicPlayer,
    requester: str
) -> None:
    """
    단일 곡 데이터를 처리하여 대기열에 추가합니다.

    Args:
        interaction: Discord 상호작용 객체
        data: 곡 데이터
        player: 음악 플레이어 인스턴스
        requester: 요청자 멘션
    """
    if not is_valid_entry(data):
        logger.error(f"[{interaction.guild.name}] 단일 곡 데이터 유효성 검사 실패")
        raise ValueError("필수 곡 정보가 누락되었습니다")

    source = create_ffmpeg_source(data, requester, FFMPEG_OPTIONS)
    await player.queue.put(source)

    logger.info(
        f"[{interaction.guild.name}] 단일 곡 추가 완료 - "
        f"제목: '{source.title}', 요청자: {interaction.user.name}"
    )
    await interaction.followup.send(
        embed=make_embed(f"✅ 대기열에 추가됨: [**{source.title}**]({source.webpage_url})")
    )


@bot.event
async def on_ready():
    """봇이 준비되었을 때 호출되는 이벤트 핸들러입니다."""
    print(f"--- 봇 정보 ---")
    print(f"봇 이름: {bot.user.name}")
    print(f"봇 ID: {bot.user.id}")
    print(f"Discord.py 버전: {discord.__version__}")
    print(f"실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("---------------")

    logger.info(f"봇 준비 완료 - {bot.user.name} ({bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"동기화된 명령어: {len(synced)}개")
        logger.info(f"슬래시 명령어 동기화 완료 - {len(synced)}개")
    except Exception as e:
        print(f"명령어 동기화 실패: {e}")
        logger.error(f"슬래시 명령어 동기화 실패 - {e}")


@bot.tree.command(name="재생", description="YouTube에서 노래/플레이리스트를 재생합니다.")
@app_commands.describe(query="재생할 노래/플레이리스트의 제목 또는 URL")
async def play(interaction: discord.Interaction, query: str):
    """
    재생 명령어 - YouTube에서 음악을 검색하고 재생합니다.

    Args:
        interaction: Discord 상호작용 객체
        query: 검색어 또는 YouTube URL
    """
    logger.info(
        f"[{interaction.guild.name}] /재생 명령어 실행 - "
        f"사용자: {interaction.user.name}, 쿼리: '{query}'"
    )
    await interaction.response.defer(thinking=True)

    player = await get_player(interaction)
    if player is None:
        logger.warning(f"[{interaction.guild.name}] 플레이어 준비 실패")
        return

    try:
        logger.debug(f"[{interaction.guild.name}] YouTube 정보 검색 시작 - 쿼리: '{query}'")
        data = await YTDLSource.create_source(query, loop=bot.loop)
        logger.debug(f"[{interaction.guild.name}] YouTube 정보 검색 완료")

    except yt_dlp.utils.DownloadError as e:
        error_str = str(e)
        logger.warning(
            f"[{interaction.guild.name}] yt-dlp 다운로드 오류 - "
            f"쿼리: '{query}', 오류: {e}"
        )

        if "is not available" in error_str or "Private video" in error_str:
            msg = "❗ 해당 영상을 찾을 수 없거나 비공개 영상입니다."
        elif "Unsupported URL" in error_str:
            msg = "❗ 지원하지 않는 URL 형식입니다."
        else:
            msg = f"❗ 영상을 가져오는 중 오류 발생: {e}"

        await interaction.followup.send(embed=make_embed(msg))
        return

    except Exception as e:
        logger.error(
            f"[{interaction.guild.name}] YouTube 정보 검색 실패 - "
            f"쿼리: '{query}', 오류: {e}",
            exc_info=True
        )
        await interaction.followup.send(
            embed=make_embed(f"❗ 음악 정보를 가져오는 중 오류 발생: {e}")
        )
        return

    is_playlist = isinstance(data, dict) and data.get("type") == "playlist"
    logger.debug(
        f"[{interaction.guild.name}] 데이터 타입 확인 - "
        f"플레이리스트: {is_playlist}"
    )
    await process_ytdl_data(interaction, data, player, is_playlist)


@bot.tree.command(name="대기열", description="현재 재생 대기열을 확인합니다.")
async def queue(interaction: discord.Interaction):
    """
    대기열 명령어 - 현재 재생 대기열을 표시합니다.

    Args:
        interaction: Discord 상호작용 객체
    """
    logger.info(
        f"[{interaction.guild.name}] /대기열 명령어 실행 - "
        f"사용자: {interaction.user.name}"
    )

    player = bot.music_players.get(interaction.guild.id)
    logger.debug(f"[{interaction.guild.name}] 플레이어 조회 결과: {player is not None}")

    if not player or not player.voice_client or not player.voice_client.is_connected():
        logger.debug(f"[{interaction.guild.name}] 플레이어가 없거나 연결되지 않음")
        await interaction.response.send_message(
            embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()

    queue_items = player.get_queue_items()
    embed = discord.Embed(title="🎶 음악 대기열", color=discord.Color.purple())

    # 현재 재생 중인 곡
    if player.current:
        duration = getattr(player.current, 'duration', None)
        duration_str = f" ({format_time(duration)})" if duration else ""
        url = getattr(player.current, 'webpage_url', '')
        current_msg = (
            f"[**{player.current.title}**]({url}){duration_str} - "
            f"{player.current.requester}"
        )
    else:
        current_msg = "없음"
    embed.add_field(name="🎵 현재 재생 중", value=current_msg, inline=False)

    # 대기열
    if not queue_items:
        queue_str = "📭 대기열이 비어있습니다."
    else:
        lines = []
        for i, song in enumerate(queue_items[:MAX_QUEUE_DISPLAY], 1):
            duration = getattr(song, 'duration', None)
            duration_str = f" ({format_time(duration)})" if duration else ""
            url = getattr(song, 'webpage_url', '')
            lines.append(
                f"{i}. [**{song.title}**]({url}){duration_str} - {song.requester}"
            )

        if len(queue_items) > MAX_QUEUE_DISPLAY:
            lines.append(f"\n... 외 {len(queue_items) - MAX_QUEUE_DISPLAY}곡 더 있음")
        queue_str = "\n".join(lines)

    embed.add_field(name=f"⏭️ 다음 곡 ({len(queue_items)}개)", value=queue_str, inline=False)

    if player.current_playlist_url:
        embed.set_footer(
            text=f"플레이리스트 자동 로딩 중... (다음 로드: {player.next_playlist_index}번째 곡)"
        )

    logger.debug(
        f"[{interaction.guild.name}] 대기열 표시 - "
        f"현재곡: {getattr(player.current, 'title', '없음')}, "
        f"대기열: {len(queue_items)}개"
    )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="삭제", description="대기열에서 지정한 순번의 곡을 제거합니다.")
@app_commands.describe(position="제거할 곡의 순번 (1부터 시작)")
async def remove(interaction: discord.Interaction, position: app_commands.Range[int, 1]):
    """
    삭제 명령어 - 대기열에서 특정 순번의 곡을 제거합니다.

    Args:
        interaction: Discord 상호작용 객체
        position: 제거할 곡의 순번 (1부터 시작)
    """
    logger.info(
        f"[{interaction.guild.name}] /삭제 명령어 실행 - "
        f"사용자: {interaction.user.name}, 순번: {position}"
    )

    player = bot.music_players.get(interaction.guild.id)

    if not player or not player.voice_client or not player.voice_client.is_connected():
        logger.debug(f"[{interaction.guild.name}] 플레이어가 없거나 연결되지 않음")
        await interaction.response.send_message(
            embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()

    queue_list = player.get_queue_items()
    logger.debug(f"[{interaction.guild.name}] 현재 대기열 크기: {len(queue_list)}개")

    if not queue_list:
        await interaction.followup.send(embed=make_embed("📭 대기열이 비어있습니다."))
        return

    if position > len(queue_list):
        logger.debug(
            f"[{interaction.guild.name}] 유효하지 않은 순번 - "
            f"요청: {position}, 최대: {len(queue_list)}"
        )
        await interaction.followup.send(
            embed=make_embed(f"❗ 유효하지 않은 순번입니다. (최대: {len(queue_list)})")
        )
        return

    try:
        removed = queue_list.pop(position - 1)
        logger.debug(
            f"[{interaction.guild.name}] 대기열에서 곡 제거 - "
            f"제목: '{removed.title}'"
        )

        # 대기열 재구성
        while not player.queue.empty():
            try:
                player.queue.get_nowait()
            except Exception:
                break

        for song in queue_list:
            await player.queue.put(song)

        logger.info(
            f"[{interaction.guild.name}] 곡 삭제 완료 - "
            f"순번: {position}, 제목: '{removed.title}', "
            f"요청자: {interaction.user.name}"
        )
        await interaction.followup.send(
            embed=make_embed(f"🗑️ 제거됨 (#{position}): **{removed.title}**")
        )

    except Exception as e:
        logger.error(
            f"[{interaction.guild.name}] 곡 삭제 실패 - {e}",
            exc_info=True
        )
        await interaction.followup.send(embed=make_embed(f"❗ 곡 제거 중 오류 발생: {e}"))


@bot.tree.command(name="스킵", description="현재 재생 중인 곡을 건너뜁니다.")
async def skip(interaction: discord.Interaction):
    """
    스킵 명령어 - 현재 재생 중인 곡을 건너뜁니다.

    Args:
        interaction: Discord 상호작용 객체
    """
    logger.info(
        f"[{interaction.guild.name}] /스킵 명령어 실행 - "
        f"사용자: {interaction.user.name}"
    )

    player = bot.music_players.get(interaction.guild.id)

    if not player or not player.voice_client or not player.voice_client.is_connected():
        logger.debug(f"[{interaction.guild.name}] 플레이어가 없거나 연결되지 않음")
        await interaction.response.send_message(
            embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."),
            ephemeral=True
        )
        return

    if player.voice_client.is_playing():
        title = getattr(player.current, 'title', '현재 곡')
        logger.info(
            f"[{interaction.guild.name}] 곡 스킵 - "
            f"제목: '{title}', 요청자: {interaction.user.name}"
        )
        player.voice_client.stop()
        await interaction.response.send_message(
            embed=make_embed(f"⏭️ '**{title}**'을(를) 건너뛰었습니다.")
        )
    else:
        logger.debug(f"[{interaction.guild.name}] 재생 중인 곡이 없음")
        await interaction.response.send_message(
            embed=make_embed("🚫 재생 중인 곡이 없습니다."),
            ephemeral=True
        )


@bot.tree.command(name="정지", description="음악 재생을 중지하고 봇을 퇴장시킵니다.")
async def stop(interaction: discord.Interaction):
    """
    정지 명령어 - 음악 재생을 중지하고 음성 채널에서 나갑니다.

    Args:
        interaction: Discord 상호작용 객체
    """
    logger.info(
        f"[{interaction.guild.name}] /정지 명령어 실행 - "
        f"사용자: {interaction.user.name}"
    )

    player = bot.music_players.get(interaction.guild.id)

    if not player or not player.voice_client or not player.voice_client.is_connected():
        logger.debug(f"[{interaction.guild.name}] 플레이어가 없거나 연결되지 않음")
        await interaction.response.send_message(
            embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."),
            ephemeral=True
        )
        return

    logger.info(f"[{interaction.guild.name}] 플레이어 정지 및 파괴 시작")
    await player.destroy(notify=False)
    await interaction.response.send_message(
        embed=make_embed("⏹️ 음악 재생을 중지하고 음성 채널 연결을 종료했습니다.")
    )


@bot.tree.command(name="현재곡", description="현재 재생 중인 곡 정보를 표시합니다.")
async def now_playing(interaction: discord.Interaction):
    """
    현재곡 명령어 - 현재 재생 중인 곡의 정보와 진행률을 표시합니다.

    Args:
        interaction: Discord 상호작용 객체
    """
    logger.info(
        f"[{interaction.guild.name}] /현재곡 명령어 실행 - "
        f"사용자: {interaction.user.name}"
    )

    player = bot.music_players.get(interaction.guild.id)

    if not player or not player.voice_client or not player.voice_client.is_connected():
        logger.debug(f"[{interaction.guild.name}] 플레이어가 없거나 연결되지 않음")
        await interaction.response.send_message(
            embed=make_embed("🚫 봇이 음성 채널에 없거나 재생 중이 아닙니다."),
            ephemeral=True
        )
        return

    if not player.current:
        logger.debug(f"[{interaction.guild.name}] 현재 재생 중인 곡 없음")
        await interaction.response.send_message(
            embed=make_embed("🚫 현재 재생 중인 곡이 없습니다."),
            ephemeral=True
        )
        return

    await interaction.response.defer()

    embed = player.build_now_playing_embed()

    # 진행률 바 추가
    playback_time = player.get_playback_time()
    duration = getattr(player.current, 'duration', None)
    if duration and playback_time is not None:
        progress = int((playback_time / duration) * 20)
        bar = '▬' * progress + '🔘' + '▬' * (19 - progress)
        embed.add_field(
            name="진행률",
            value=f"`{format_time(playback_time)} / {format_time(duration)}`\n`{bar}`",
            inline=False
        )

    logger.debug(
        f"[{interaction.guild.name}] 현재곡 정보 표시 - "
        f"제목: '{player.current.title}', "
        f"진행: {format_time(playback_time)}/{format_time(duration)}"
    )
    await interaction.followup.send(embed=embed)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):
    """
    음성 상태 변경 이벤트 핸들러입니다.

    봇이 음성 채널에서 연결이 끊기면 플레이어를 정리합니다.

    Args:
        member: 상태가 변경된 멤버
        before: 이전 음성 상태
        after: 현재 음성 상태
    """
    logger.debug(
        f"[{member.guild.name}] 음성 상태 변경 - "
        f"멤버: {member.name}, "
        f"이전 채널: {before.channel.name if before.channel else '없음'}, "
        f"현재 채널: {after.channel.name if after.channel else '없음'}"
    )

    # 봇이 음성 채널에서 나간 경우
    if member.id == bot.user.id and before.channel and not after.channel:
        guild_id = member.guild.id
        if guild_id in bot.music_players:
            player = bot.music_players[guild_id]
            logger.info(
                f"[{member.guild.name}] 봇 음성 연결 해제 감지 - "
                f"채널: {before.channel.name}, 플레이어 정리 시작"
            )
            await player.destroy(notify=False)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    """
    슬래시 명령어 오류 핸들러입니다.

    Args:
        interaction: Discord 상호작용 객체
        error: 발생한 오류
    """
    cmd_name = interaction.command.name if interaction.command else "알 수 없음"
    logger.error(
        f"[{interaction.guild.name}] 명령어 오류 발생 - "
        f"명령어: {cmd_name}, 오류: {error}",
        exc_info=True
    )

    # 오류 유형별 메시지
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
        msg = f"명령어 처리 중 오류가 발생했습니다: {error}"

    embed = make_embed(f"❗ {msg}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.NotFound:
        logger.warning(
            f"[{interaction.guild.name}] 오류 메시지 전송 실패 - "
            "상호작용을 찾을 수 없음"
        )
    except Exception as e:
        logger.error(
            f"[{interaction.guild.name}] 오류 메시지 전송 중 예외 발생 - {e}"
        )


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("오류: BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
        logger.critical("BOT_TOKEN 환경 변수가 설정되지 않았습니다. 봇을 시작할 수 없습니다.")
    else:
        logger.info("봇 시작 중...")
        try:
            bot.run(BOT_TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.critical("로그인 실패. BOT_TOKEN을 확인해주세요.")
        except Exception as e:
            logger.critical(f"봇 실행 중 오류 발생 - {e}", exc_info=True)
