import discord
from typing import Dict, Any

def is_valid_entry(entry: Dict[str, Any]) -> bool:
    return all(key in entry for key in ("url", "title", "webpage_url"))

def create_ffmpeg_source(
    entry: Dict[str, Any],
    requester: str,
    ffmpeg_options: Dict[str, Any]
) -> discord.FFmpegPCMAudio:
    source = discord.FFmpegPCMAudio(entry["url"], **ffmpeg_options)
    source.title = entry["title"]
    source.webpage_url = entry.get("webpage_url", "")
    source.duration = entry.get("duration")
    source.requester = requester
    return source

def make_embed(msg: str, color: discord.Color = discord.Color.purple()) -> discord.Embed:
    """간단한 설명 메시지용 임베드 생성"""
    return discord.Embed(description=msg, color=color)