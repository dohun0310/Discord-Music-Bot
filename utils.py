"""
유틸리티 모듈

공통으로 사용되는 헬퍼 함수들을 정의합니다.
"""

import logging
from typing import Any, Optional

import discord
from typing_extensions import TypedDict

from config import Colors, Emoji

logger = logging.getLogger('discord.bot.utils')


class AudioEntry(TypedDict, total=False):
    """
    오디오 항목의 타입 정의

    Attributes:
        url: 오디오 스트림 URL
        title: 곡 제목
        webpage_url: 원본 웹페이지 URL
        duration: 곡 길이 (초 단위)
        thumbnail: 썸네일 URL
    """
    url: str
    title: str
    webpage_url: str
    duration: Optional[float]
    thumbnail: Optional[str]


def is_valid_entry(entry: dict[str, Any]) -> bool:
    """
    오디오 항목이 필수 키를 모두 가지고 있는지 확인합니다.

    Args:
        entry: 검증할 오디오 항목 딕셔너리

    Returns:
        필수 키가 모두 존재하면 True, 아니면 False
    """
    required_keys = ("url", "title", "webpage_url")
    is_valid = all(key in entry for key in required_keys)

    if not is_valid:
        missing = [k for k in required_keys if k not in entry]
        logger.debug(f"항목 검증 실패 - 누락된 키: {missing}, 제목: {entry.get('title', '알 수 없음')}")

    return is_valid


def create_ffmpeg_source(
    entry: AudioEntry,
    requester: str,
    ffmpeg_options: dict[str, Any]
) -> discord.FFmpegPCMAudio:
    """
    FFmpegPCMAudio 소스 객체를 생성합니다.

    Args:
        entry: 오디오 항목 정보
        requester: 요청자 멘션 문자열
        ffmpeg_options: FFmpeg 옵션 딕셔너리

    Returns:
        메타데이터가 추가된 FFmpegPCMAudio 객체
    """
    logger.debug(f"FFmpeg 소스 생성 - 제목: '{entry.get('title')}', 요청자: {requester}")

    source = discord.FFmpegPCMAudio(entry["url"], **ffmpeg_options)
    source.title = entry["title"]
    source.webpage_url = entry.get("webpage_url", "")
    source.duration = entry.get("duration")
    source.thumbnail = entry.get("thumbnail")
    source.requester = requester

    logger.debug(f"FFmpeg 소스 생성 완료 - 제목: '{source.title}', 길이: {source.duration}초")
    return source


def make_embed(
    msg: str,
    color: discord.Color = Colors.PRIMARY,
    title: Optional[str] = None
) -> discord.Embed:
    """
    메시지용 Discord Embed를 생성합니다.

    Args:
        msg: 임베드에 표시할 메시지
        color: 임베드 색상
        title: 임베드 제목 (선택)

    Returns:
        생성된 Discord Embed 객체
    """
    embed = discord.Embed(description=msg, color=color)
    if title:
        embed.title = title
    return embed


def make_success_embed(msg: str) -> discord.Embed:
    """성공 메시지 임베드를 생성합니다."""
    return make_embed(f"{Emoji.SUCCESS} {msg}", Colors.SUCCESS)


def make_error_embed(msg: str) -> discord.Embed:
    """에러 메시지 임베드를 생성합니다."""
    return make_embed(f"{Emoji.ERROR} {msg}", Colors.ERROR)


def make_warning_embed(msg: str) -> discord.Embed:
    """경고 메시지 임베드를 생성합니다."""
    return make_embed(f"{Emoji.WARNING} {msg}", Colors.WARNING)


def make_info_embed(msg: str) -> discord.Embed:
    """정보 메시지 임베드를 생성합니다."""
    return make_embed(f"{Emoji.INFO} {msg}", Colors.INFO)


def format_time(seconds: Optional[float]) -> str:
    """
    초 단위 시간을 읽기 쉬운 문자열로 변환합니다.

    Args:
        seconds: 변환할 초 단위 시간

    Returns:
        "HH:MM:SS" 또는 "MM:SS" 형식의 문자열
        None인 경우 "--:--" 반환
    """
    if seconds is None:
        return "--:--"

    total_seconds = int(seconds)
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def create_progress_bar(current: float, total: float, length: int = 12) -> str:
    """
    진행률 바를 생성합니다.

    Args:
        current: 현재 값
        total: 전체 값
        length: 바의 길이 (기본 12)

    Returns:
        진행률 바 문자열
    """
    if total <= 0:
        return "▬" * length

    progress = min(current / total, 1.0)
    filled = int(progress * length)

    # 더 예쁜 진행률 바
    bar = "▬" * filled + "🔘" + "▬" * (length - filled - 1)
    return bar


def truncate_string(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    문자열이 최대 길이를 초과하면 잘라냅니다.

    Args:
        text: 원본 문자열
        max_length: 최대 길이
        suffix: 잘릴 경우 붙일 접미사

    Returns:
        처리된 문자열
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def get_youtube_thumbnail(video_id: str, quality: str = "maxresdefault") -> str:
    """
    YouTube 비디오 ID로 썸네일 URL을 생성합니다.

    Args:
        video_id: YouTube 비디오 ID
        quality: 썸네일 품질 (maxresdefault, hqdefault, mqdefault, sddefault)

    Returns:
        썸네일 URL
    """
    return f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"


def extract_video_id(url: str) -> Optional[str]:
    """
    YouTube URL에서 비디오 ID를 추출합니다.

    Args:
        url: YouTube URL

    Returns:
        비디오 ID 또는 None
    """
    import re

    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None
