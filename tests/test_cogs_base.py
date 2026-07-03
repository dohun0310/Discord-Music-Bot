from app.cogs.base import MusicCog
from app.config import Settings
from app.ui.embeds import EmbedFactory


class _Response:
    def __init__(self):
        self.sent = []
        self._done = False

    def is_done(self):
        return self._done

    async def send_message(self, *, embed, ephemeral=False):
        self.sent.append((embed, ephemeral))
        self._done = True


class _Followup:
    def __init__(self, sink):
        self.sink = sink

    async def send(self, *, embed, ephemeral=False):
        self.sink.append((embed, ephemeral))


class _VoiceState:
    def __init__(self, channel):
        self.channel = channel


class _User:
    def __init__(self, channel):
        self.voice = _VoiceState(channel) if channel else None


class _Guild:
    id = 1
    name = "g"


class _Interaction:
    def __init__(self, user_channel=None):
        self.guild = _Guild()
        self.user = _User(user_channel)
        self.response = _Response()
        self.followup = _Followup(self.response.sent)


class _Player:
    def __init__(self, channel="보이스A"):
        self._channel = channel

    def is_connected(self):
        return True

    @property
    def voice_channel(self):
        return self._channel


class _Registry:
    def __init__(self, player):
        self.player = player

    def get(self, guild_id):
        return self.player


def _cog(player):
    return MusicCog(
        bot=object(), registry=_Registry(player), embeds=EmbedFactory(),
        settings=Settings(bot_token=None, log_level="INFO"),
    )


async def test_require_control_rejects_when_no_player():
    cog = _cog(player=None)
    interaction = _Interaction(user_channel="보이스A")
    assert await cog.require_control(interaction) is None
    assert len(interaction.response.sent) == 1


async def test_require_control_rejects_other_channel_user():
    cog = _cog(player=_Player("보이스A"))
    interaction = _Interaction(user_channel="보이스B")
    assert await cog.require_control(interaction) is None
    embed, ephemeral = interaction.response.sent[0]
    assert ephemeral is True
    assert "같은 음성 채널" in embed.description


async def test_require_control_rejects_user_not_in_voice():
    cog = _cog(player=_Player("보이스A"))
    interaction = _Interaction(user_channel=None)
    assert await cog.require_control(interaction) is None


async def test_require_control_allows_same_channel():
    player = _Player("보이스A")
    cog = _cog(player=player)
    interaction = _Interaction(user_channel="보이스A")
    assert await cog.require_control(interaction) is player
    assert interaction.response.sent == []


async def test_require_player_no_channel_restriction():
    player = _Player("보이스A")
    cog = _cog(player=player)
    interaction = _Interaction(user_channel=None)
    assert await cog.require_player(interaction) is player


async def test_respond_uses_followup_after_done():
    cog = _cog(player=None)
    interaction = _Interaction()
    await cog.respond(interaction, cog.embeds.info("첫번째"))
    await cog.respond(interaction, cog.embeds.info("두번째"))
    assert len(interaction.response.sent) == 2  # 두번째는 followup 경유
