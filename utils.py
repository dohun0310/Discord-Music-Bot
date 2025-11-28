import discord
import logging
from typing import Dict, Any

logger = logging.getLogger('discord.bot.utils')

def is_valid_entry(entry: Dict[str, Any]) -> bool:
    """항목이 필수 키를 모두 가지고 있는지 확인"""
    required_keys = ("url", "title", "webpage_url")
    is_valid = all(key in entry for key in required_keys)
    if not is_valid:
        missing = [k for k in required_keys if k not in entry]
        logger.debug(f"is_valid_entry: 유효하지 않음. 누락된 키: {missing}, title: {entry.get('title', 'N/A')}")
    return is_valid

def create_ffmpeg_source(
    entry: Dict[str, Any],
    requester: str,
    ffmpeg_options: Dict[str, Any]
) -> discord.FFmpegPCMAudio:
    """FFmpegPCMAudio 소스 객체 생성"""
    logger.debug(f"create_ffmpeg_source: title='{entry.get('title')}', requester={requester}")
    logger.debug(f"create_ffmpeg_source: url={entry.get('url', 'N/A')[:80]}...")
    
    source = discord.FFmpegPCMAudio(entry["url"], **ffmpeg_options)
    source.title = entry["title"]
    source.webpage_url = entry.get("webpage_url", "")
    source.duration = entry.get("duration")
    source.requester = requester
    
    logger.debug(f"create_ffmpeg_source 완료: title='{source.title}', duration={source.duration}")
    return source

def make_embed(msg: str, color: discord.Color = discord.Color.purple()) -> discord.Embed:
    """간단한 설명 메시지용 임베드 생성"""
    logger.debug(f"make_embed: msg='{msg[:50]}...' (len={len(msg)})")
    return discord.Embed(description=msg, color=color)