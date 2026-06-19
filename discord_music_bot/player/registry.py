"""guild_id → GuildPlayer 수명주기 관리. bot.music_players 딕셔너리를 대체한다."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import discord
from discord.ext import commands

from ..config import Settings
from ..services.audio import AudioSourceFactory
from ..services.resolver import TrackResolver
from ..ui.embeds import EmbedFactory
from .guild_player import GuildPlayer

logger = logging.getLogger("discord.bot.registry")


class PlayerRegistry:
    """플레이어 생성에 필요한 의존성을 보관하고 새 GuildPlayer에 주입한다.

    player_factory를 주입하면(테스트용) GuildPlayer 대신 대체 구현을 생성한다.
    """

    def __init__(
        self, *, bot: commands.Bot = None, settings: Settings = None,
        resolver: TrackResolver = None, source_factory: AudioSourceFactory = None,
        embeds: EmbedFactory = None, player_factory: Optional[Callable] = None,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._resolver = resolver
        self._source_factory = source_factory
        self._embeds = embeds
        self._player_factory = player_factory or self._default_factory
        self._players: dict[int, object] = {}

    def _default_factory(self, *, guild, text_channel, voice_client, on_destroy):
        return GuildPlayer(
            guild=guild, text_channel=text_channel, voice_client=voice_client,
            bot=self._bot, settings=self._settings, resolver=self._resolver,
            source_factory=self._source_factory, embeds=self._embeds, on_destroy=on_destroy,
        )

    def get(self, guild_id: int):
        return self._players.get(guild_id)

    def create(self, *, guild: discord.Guild, text_channel, voice_client):
        player = self._player_factory(
            guild=guild, text_channel=text_channel, voice_client=voice_client,
            on_destroy=self._remove,
        )
        self._players[guild.id] = player
        return player

    def all(self) -> list:
        return list(self._players.values())

    def _remove(self, guild_id: int) -> None:
        self._players.pop(guild_id, None)
