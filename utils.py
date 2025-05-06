import discord
import asyncio
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

def make_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=msg, color=discord.Color.purple())

async def send_temp(interaction: discord.Interaction, embed: discord.Embed, delay: int = 10) -> None:
    msg = await interaction.followup.send(embed=embed, wait=True)
    await asyncio.sleep(delay)
    await msg.delete()