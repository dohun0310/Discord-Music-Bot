from app.player.registry import PlayerRegistry


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
        self.name = "g"


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


class _VoiceState:
    def __init__(self, channel):
        self.channel = channel


class _Member:
    def __init__(self, mid, guild):
        self.id = mid
        self.guild = guild


class _EventPlayer:
    def __init__(self):
        self.destroyed = False
        self.pinged = 0

    async def destroy(self, notify=True):
        self.destroyed = True

    def on_voice_members_changed(self):
        self.pinged += 1


def _registry_with_player(gid=1):
    player = _EventPlayer()

    def factory(*, guild, text_channel, voice_client, on_destroy):
        return player

    reg = PlayerRegistry(player_factory=factory)
    reg.create(guild=_Guild(gid), text_channel=object(), voice_client=object())
    return reg, player


async def test_bot_disconnect_destroys_player():
    reg, player = _registry_with_player()
    member = _Member(99, _Guild(1))
    await reg.notify_voice_state(member, _VoiceState("음성1"), _VoiceState(None), bot_user_id=99)
    assert player.destroyed is True


async def test_member_change_pings_player():
    reg, player = _registry_with_player()
    member = _Member(5, _Guild(1))
    await reg.notify_voice_state(member, _VoiceState("음성1"), _VoiceState(None), bot_user_id=99)
    assert player.destroyed is False
    assert player.pinged == 1


async def test_voice_event_without_player_is_noop():
    reg = PlayerRegistry(player_factory=lambda **kw: None)
    member = _Member(5, _Guild(42))
    await reg.notify_voice_state(member, _VoiceState(None), _VoiceState("음성1"), bot_user_id=99)
