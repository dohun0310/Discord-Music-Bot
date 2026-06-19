from discord_music_bot.player.registry import PlayerRegistry


class _FakePlayer:
    def __init__(self, guild_id):
        self.guild_id = guild_id


def _registry():
    created = []

    def factory(*, guild, text_channel, voice_client, on_destroy):
        player = _FakePlayer(guild.id)
        player._on_destroy = on_destroy
        created.append(player)
        return player

    reg = PlayerRegistry(player_factory=factory)
    return reg, created


class _Guild:
    def __init__(self, gid):
        self.id = gid


def test_create_and_get():
    reg, _ = _registry()
    player = reg.create(guild=_Guild(1), text_channel=object(), voice_client=object())
    assert reg.get(1) is player
    assert reg.get(999) is None


def test_all_returns_players():
    reg, _ = _registry()
    reg.create(guild=_Guild(1), text_channel=object(), voice_client=object())
    reg.create(guild=_Guild(2), text_channel=object(), voice_client=object())
    assert len(reg.all()) == 2


def test_on_destroy_callback_removes():
    reg, created = _registry()
    reg.create(guild=_Guild(1), text_channel=object(), voice_client=object())
    created[0]._on_destroy(1)  # 플레이어가 destroy 시 호출하는 콜백
    assert reg.get(1) is None
