from app.player.notifier import ChannelNotifier
from app.ui.embeds import EmbedFactory


class _OkChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *, embed):
        self.sent.append(embed)


class _FailChannel:
    async def send(self, *, embed):
        raise RuntimeError("Forbidden")


async def test_send_success_returns_true():
    ch = _OkChannel()
    n = ChannelNotifier(ch, guild_name="g")
    assert await n.send(EmbedFactory().info("hi")) is True
    assert len(ch.sent) == 1


async def test_send_failure_swallowed_returns_false():
    n = ChannelNotifier(_FailChannel(), guild_name="g")
    assert await n.send(EmbedFactory().info("hi")) is False


async def test_set_channel_switches_target():
    a, b = _OkChannel(), _OkChannel()
    n = ChannelNotifier(a, guild_name="g")
    n.set_channel(b)
    await n.send(EmbedFactory().info("hi"))
    assert len(a.sent) == 0 and len(b.sent) == 1
