"""모든 Discord 임베드 생성을 담당하는 표현 계층."""

from __future__ import annotations

from typing import Optional

import discord

from ..config import Colors, Emoji
from ..domain.models import RepeatMode, Track
from .formatting import create_progress_bar, format_time, truncate_string


class EmbedFactory:
    """상태가 없는 임베드 빌더. 도메인 값/원시값만 받아 Embed를 만든다."""

    # ----- 일반 메시지 -----
    def message(
        self, msg: str, color: discord.Color = Colors.PRIMARY,
        title: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(description=msg, color=color)
        if title:
            embed.title = title
        return embed

    def success(self, msg: str) -> discord.Embed:
        return self.message(f"{Emoji.SUCCESS} {msg}", Colors.SUCCESS)

    def error(self, msg: str) -> discord.Embed:
        return self.message(f"{Emoji.ERROR} {msg}", Colors.ERROR)

    def warning(self, msg: str) -> discord.Embed:
        return self.message(f"{Emoji.WARNING} {msg}", Colors.WARNING)

    def info(self, msg: str) -> discord.Embed:
        return self.message(f"{Emoji.INFO} {msg}", Colors.INFO)

    # ----- 곡/대기열 -----
    def _status_parts(self, volume: float, repeat_mode: RepeatMode) -> list[str]:
        parts = [f"{Emoji.VOLUME_HIGH} `{volume:.0%}`"]
        if repeat_mode == RepeatMode.ONE:
            parts.append(f"{Emoji.REPEAT_ONE} 한곡")
        elif repeat_mode == RepeatMode.ALL:
            parts.append(f"{Emoji.REPEAT} 전체")
        return parts

    def now_playing(
        self, track: Track, *, volume: float, repeat_mode: RepeatMode, queue_size: int,
    ) -> discord.Embed:
        embed = discord.Embed(title=f"{Emoji.MUSIC} 현재 재생 중", color=Colors.MUSIC)
        desc = f"**[{truncate_string(track.title, 50)}]({track.webpage_url})**\n\n"
        if track.duration:
            desc += f"{Emoji.TIME} `{format_time(track.duration)}`\n"
        desc += f"{Emoji.USER} {track.requester}\n"
        desc += " ".join(self._status_parts(volume, repeat_mode))
        embed.description = desc
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if queue_size > 0:
            embed.set_footer(text=f"대기열에 {queue_size}곡 있음")
        return embed

    def progress(
        self, track: Track, *, volume: float, repeat_mode: RepeatMode,
        queue_size: int, position: Optional[float],
    ) -> discord.Embed:
        embed = self.now_playing(
            track, volume=volume, repeat_mode=repeat_mode, queue_size=queue_size
        )
        if track.duration and position is not None:
            bar = create_progress_bar(position, track.duration, 12)
            embed.add_field(
                name="진행률",
                value=f"`{format_time(position)}` {bar} `{format_time(track.duration)}`",
                inline=False,
            )
        return embed

    def track_added(self, track: Track, *, queue_position: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"{Emoji.SUCCESS} 대기열에 추가됨",
            description=f"**[{truncate_string(track.title, 50)}]({track.webpage_url})**",
            color=Colors.SUCCESS,
        )
        if track.duration:
            embed.add_field(name="길이", value=f"`{format_time(track.duration)}`", inline=True)
        embed.add_field(name="요청자", value=track.requester, inline=True)
        embed.add_field(name="대기열 위치", value=f"`#{queue_position}`", inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    def playlist_added(self, title: str, *, count: int, requester: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"{Emoji.PLAYLIST} 플레이리스트 추가됨",
            description=(
                f"**{truncate_string(title, 50)}**\n\n"
                f"{Emoji.MUSIC} `{count}곡` 추가됨\n{Emoji.USER} {requester}"
            ),
            color=Colors.SUCCESS,
        )
        embed.set_footer(text="나머지 곡은 재생 시 자동으로 로드됩니다")
        return embed

    def queue(
        self, *, current: Optional[Track], position: Optional[float], paused: bool,
        snapshot: list[Track], volume: float, repeat_mode: RepeatMode, max_display: int,
    ) -> discord.Embed:
        embed = discord.Embed(title=f"{Emoji.QUEUE} 음악 대기열", color=Colors.QUEUE)

        if current:
            info = f"**[{truncate_string(current.title, 40)}]({current.webpage_url})**\n"
            if current.duration and position is not None:
                bar = create_progress_bar(position, current.duration, 10)
                info += f"`{format_time(position)}` {bar} `{format_time(current.duration)}`\n"
            info += f"{Emoji.USER} {current.requester}"
            icon = Emoji.PAUSE if paused else Emoji.PLAY
            embed.add_field(name=f"{icon} 현재 재생 중", value=info, inline=False)
        else:
            embed.add_field(name=f"{Emoji.MUSIC} 현재 재생 중", value="없음", inline=False)

        if not snapshot:
            queue_str = f"{Emoji.EMPTY} 대기열이 비어있습니다."
        else:
            lines = []
            for i, song in enumerate(snapshot[:max_display], 1):
                dur = f" `{format_time(song.duration)}`" if song.duration else ""
                lines.append(f"`{i}.` **{truncate_string(song.title, 35)}**{dur}")
            if len(snapshot) > max_display:
                lines.append(f"\n*... 외 {len(snapshot) - max_display}곡*")
            queue_str = "\n".join(lines)

        embed.add_field(
            name=f"{Emoji.PLAYLIST} 다음 곡 ({len(snapshot)}개)", value=queue_str, inline=False
        )
        embed.set_footer(text=" │ ".join(self._status_parts(volume, repeat_mode)))
        if current and current.thumbnail:
            embed.set_thumbnail(url=current.thumbnail)
        return embed
