"""GuildPlayer 오케스트레이션 테스트 (가짜 voice/채널/리졸버 사용)."""

import asyncio
import time

from app.config import Settings
from app.domain.models import RepeatMode, Track
from app.player.guild_player import GuildPlayer
from app.ui.embeds import EmbedFactory


def _track(title, duration=100.0, resolved_at=None):
    return Track(
        title=title, stream_url="http://s/" + title, webpage_url="http://w/" + title,
        duration=duration, thumbnail=None, uploader="u", requester="@r",
        resolved_at=resolved_at,
    )


def _settings(**kw):
    base = dict(bot_token=None, log_level="INFO", idle_timeout=1, queue_timeout=60)
    base.update(kw)
    return Settings(**base)


class _Member:
    def __init__(self, bot=False):
        self.bot = bot


class _VoiceChannel:
    def __init__(self, humans=1):
        self.members = [_Member(bot=True)] + [_Member() for _ in range(humans)]


class _FakeVoiceClient:
    def __init__(self, channel):
        self.channel = channel
        self._connected = True
        self._playing = False
        self._paused = False
        self.play_calls = []
        self._after = None

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    def play(self, source, *, after=None, **kw):
        self._playing = True
        self._after = after
        self.play_calls.append(source)

    def stop(self):
        was_active = self._playing or self._paused
        self._playing = False
        self._paused = False
        if was_active and self._after:
            after, self._after = self._after, None
            after(None)

    def pause(self):
        self._playing, self._paused = False, True

    def resume(self):
        self._playing, self._paused = True, False

    async def disconnect(self, force=False):
        self._connected = False

    def finish_track(self, error=None):
        """자연 종료 시뮬레이션."""
        self._playing = False
        if self._after:
            after, self._after = self._after, None
            after(error)


class _Channel:
    def __init__(self):
        self.sent = []

    async def send(self, *, embed):
        self.sent.append(embed)


class _Guild:
    def __init__(self):
        self.id = 1
        self.name = "테스트길드"


class _Source:
    def __init__(self, url):
        self.url = url


class _SourceFactory:
    def __init__(self, fail=False):
        self.fail = fail
        self.created = []

    def create(self, track, volume):
        if self.fail:
            raise RuntimeError("소스 생성 실패")
        src = _Source(track.stream_url)
        self.created.append(src)
        return src


class _Resolver:
    def __init__(self):
        self.refreshed = []

    async def resolve(self, query, requester):
        raise AssertionError("테스트에서 resolve 호출 금지")

    async def load_playlist_batch(self, url, start_index, requester):
        return []

    async def refresh(self, track):
        self.refreshed.append(track.title)
        return _track(track.title + "-새", resolved_at=time.monotonic())


async def _wait_until(pred, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        if loop.time() > end:
            raise AssertionError("조건 시간 초과")
        await asyncio.sleep(0.01)


def _make_player(settings=None, source_factory=None, humans=1):
    channel = _Channel()
    vc = _FakeVoiceClient(_VoiceChannel(humans=humans))
    destroyed = []
    presence = []

    async def set_presence(track):
        presence.append(track)

    resolver = _Resolver()
    player = GuildPlayer(
        guild=_Guild(), text_channel=channel, voice_client=vc,
        settings=settings or _settings(),
        resolver=resolver, source_factory=source_factory or _SourceFactory(),
        embeds=EmbedFactory(), set_presence=set_presence,
        on_destroy=destroyed.append,
    )
    return player, vc, channel, destroyed, presence, resolver


async def test_plays_added_track_and_announces():
    player, vc, channel, _, presence, _ = _make_player()
    try:
        player.add_track(_track("첫곡"))
        await _wait_until(lambda: vc.is_playing())
        assert player.current.title == "첫곡"
        assert len(channel.sent) == 1  # now_playing 임베드
        assert presence and presence[-1].title == "첫곡"
    finally:
        await player.destroy(notify=False)


async def test_skip_keeps_repeat_one_and_moves_on():
    player, vc, _, _, _, _ = _make_player()
    try:
        player.add_track(_track("한곡"))
        player.add_track(_track("두곡"))
        await _wait_until(lambda: player.current and player.current.title == "한곡")
        player.toggle_repeat()  # ALL
        player.toggle_repeat()  # ONE
        assert player.repeat_mode == RepeatMode.ONE
        skipped = player.skip()
        assert skipped.title == "한곡"
        await _wait_until(lambda: player.current and player.current.title == "두곡")
        assert player.repeat_mode == RepeatMode.ONE  # 반복 모드 유지
    finally:
        await player.destroy(notify=False)


async def test_pause_freezes_playback_position():
    player, vc, _, _, _, _ = _make_player()
    try:
        player.add_track(_track("곡"))
        await _wait_until(lambda: vc.is_playing())
        assert await player.pause() is True
        pos1 = player.playback_position()
        await asyncio.sleep(0.05)
        pos2 = player.playback_position()
        assert pos1 == pos2
        assert await player.resume() is True
    finally:
        await player.destroy(notify=False)


async def test_empty_channel_grace_destroys():
    player, vc, channel, destroyed, _, _ = _make_player(
        settings=_settings(idle_timeout=0), humans=1,
    )
    try:
        player.add_track(_track("곡"))
        await _wait_until(lambda: vc.is_playing())
        vc.channel.members = [m for m in vc.channel.members if m.bot]  # 전원 퇴장
        player.on_voice_members_changed()
        await _wait_until(lambda: destroyed == [1])
    finally:
        await player.destroy(notify=False)


async def test_empty_channel_grace_cancelled_on_rejoin():
    player, vc, channel, destroyed, _, _ = _make_player(
        settings=_settings(idle_timeout=60), humans=1,
    )
    try:
        player.add_track(_track("곡"))
        await _wait_until(lambda: vc.is_playing())
        vc.channel.members = [m for m in vc.channel.members if m.bot]
        player.on_voice_members_changed()
        await _wait_until(lambda: len(channel.sent) >= 2)  # 빈 채널 경고 전송됨
        vc.channel.members.append(_Member())  # 복귀
        player.on_voice_members_changed()
        await asyncio.sleep(0.05)
        assert destroyed == []  # 파괴되지 않음
    finally:
        await player.destroy(notify=False)


async def test_consecutive_failures_stop_playback():
    factory = _SourceFactory(fail=True)
    player, vc, channel, destroyed, _, _ = _make_player(
        settings=_settings(max_consecutive_failures=2), source_factory=factory,
    )
    player.add_track(_track("죽은곡1"))
    player.add_track(_track("죽은곡2"))
    player.add_track(_track("죽은곡3"))
    await _wait_until(lambda: destroyed == [1])
    assert not vc.is_connected()


async def test_expired_stream_url_refreshed_before_play():
    player, vc, _, _, _, resolver = _make_player(
        settings=_settings(stream_url_ttl=1),
    )
    try:
        old = time.monotonic() - 999.0
        player.add_track(_track("만료곡", resolved_at=old))
        await _wait_until(lambda: vc.is_playing())
        assert resolver.refreshed == ["만료곡"]
        assert player.current.title == "만료곡-새"
    finally:
        await player.destroy(notify=False)


async def test_fresh_or_unstamped_track_not_refreshed():
    player, vc, _, _, _, resolver = _make_player()
    try:
        player.add_track(_track("일반곡", resolved_at=None))
        await _wait_until(lambda: vc.is_playing())
        assert resolver.refreshed == []
    finally:
        await player.destroy(notify=False)


async def test_destroy_is_idempotent_and_cleans_up():
    player, vc, _, destroyed, presence, _ = _make_player()
    player.add_track(_track("곡"))
    await _wait_until(lambda: vc.is_playing())
    await player.destroy(notify=False)
    await player.destroy(notify=False)
    assert destroyed == [1]
    assert not vc.is_connected()
    assert presence[-1] is None  # presence 해제


async def test_playlist_autoload_feeds_queue():
    class _BatchResolver(_Resolver):
        def __init__(self):
            super().__init__()
            self.batch_calls = 0

        async def load_playlist_batch(self, url, start_index, requester):
            self.batch_calls += 1
            if self.batch_calls > 1:
                return []
            return [_track("자동%d" % i) for i in range(3)]

    channel = _Channel()
    vc = _FakeVoiceClient(_VoiceChannel(humans=1))
    resolver = _BatchResolver()

    async def set_presence(track):
        pass

    player = GuildPlayer(
        guild=_Guild(), text_channel=channel, voice_client=vc,
        settings=_settings(), resolver=resolver, source_factory=_SourceFactory(),
        embeds=EmbedFactory(), set_presence=set_presence, on_destroy=lambda gid: None,
    )
    try:
        player.set_playlist("http://list", 2, "@r")
        await _wait_until(lambda: vc.is_playing())
        assert resolver.batch_calls >= 1
        assert player.current.title.startswith("자동")
    finally:
        await player.destroy(notify=False)
