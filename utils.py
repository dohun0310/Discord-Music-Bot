"""
유틸리티 모듈

공통으로 사용되는 헬퍼 함수들을 정의합니다.
"""

import logging
from typing import Any, Optional

import discord
from typing_extensions import TypedDict

logger = logging.getLogger('discord.bot.utils')


class AudioEntry(TypedDict, total=False):
    """
    오디오 항목의 타입 정의

    Attributes:
        url: 오디오 스트림 URL
        title: 곡 제목
        webpage_url: 원본 웹페이지 URL
        duration: 곡 길이 (초 단위)
    """
    url: str
    title: str
    webpage_url: str
    duration: Optional[float]


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
    source.requester = requester

    logger.debug(f"FFmpeg 소스 생성 완료 - 제목: '{source.title}', 길이: {source.duration}초")
    return source


def make_embed(msg: str, color: discord.Color = discord.Color.purple()) -> discord.Embed:
    """
    간단한 메시지용 Discord Embed를 생성합니다.

    Args:
        msg: 임베드에 표시할 메시지
        color: 임베드 색상 (기본값: 보라색)

    Returns:
        생성된 Discord Embed 객체
    """
    return discord.Embed(description=msg, color=color)


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
