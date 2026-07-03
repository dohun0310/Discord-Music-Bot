"""guild_id → GuildPlayer 수명주기 관리 + 음성 상태 이벤트 라우팅."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import discord

from ..config import Settings
from ..services.audio import AudioSourceFactory
from ..services.resolver import TrackResolver
from ..ui.embeds import EmbedFactory
from .guild_player import GuildPlayer, SetPresence

logger = logging.getLogger(__name__)

PlayerFactory = Callable[..., GuildPlayer]


class PlayerRegistry:
    """플레이어 생성 의존성을 보관하고 새 GuildPlayer에 주입한다.

    player_factory 주입 시(테스트용) 나머지 의존성 없이 동작한다. 기본 팩토리를
    쓰려면 settings/resolver/source_factory/embeds/set_presence가 모두 필요하다.
    """

    def __init__(
        self, *, settings: Optional[Settings] = None,
        resolver: Optional[TrackResolver] = None,
        source_factory: Optional[AudioSourceFactory] = None,
        embeds: Optional[EmbedFactory] = None,
        set_presence: Optional[SetPresence] = None,
        player_factory: Optional[PlayerFactory] = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._source_factory = source_factory
        self._embeds = embeds
        self._set_presence = set_presence
        self._player_factory = player_factory or self._default_factory
        self._players: dict[int, GuildPlayer] = {}

    def _default_factory(
        self, *, guild: discord.Guild, text_channel, voice_client, on_destroy,
    ) -> GuildPlayer:
        deps = (self._settings, self._resolver, self._source_factory,
                self._embeds, self._set_presence)
        if any(dep is None for dep in deps):
            raise RuntimeError("PlayerRegistry 의존성이 조립되지 않았습니다.")
        return GuildPlayer(
            guild=guild, text_channel=text_channel, voice_client=voice_client,
            settings=self._settings, resolver=self._resolver,
            source_factory=self._source_factory, embeds=self._embeds,
            set_presence=self._set_presence, on_destroy=on_destroy,
        )

    def get(self, guild_id: int) -> Optional[GuildPlayer]:
        return self._players.get(guild_id)

    def create(
        self, *, guild: discord.Guild, text_channel, voice_client,
    ) -> GuildPlayer:
        player = self._player_factory(
            guild=guild, text_channel=text_channel, voice_client=voice_client,
            on_destroy=self._remove,
        )
        self._players[guild.id] = player
        return player

    def all(self) -> list[GuildPlayer]:
        return list(self._players.values())

    async def notify_voice_state(
        self, member, before, after, bot_user_id: int,
    ) -> None:
        """음성 상태 변경을 해당 길드 플레이어에 라우팅한다."""
        player = self._players.get(member.guild.id)
        if player is None:
            return
        if member.id == bot_user_id and before.channel and not after.channel:
            logger.info("[%s] 봇 음성 연결 해제 감지 - 플레이어 정리", member.guild.name)
            await player.destroy(notify=False)
            return
        player.on_voice_members_changed()

    def _remove(self, guild_id: int) -> None:
        self._players.pop(guild_id, None)
