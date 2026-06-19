from discord_music_bot.domain.models import RepeatMode, Track


def _track(**kw):
    base = dict(
        title="t", stream_url="http://s", webpage_url="http://w",
        duration=10.0, thumbnail=None, uploader="u", requester="@r",
    )
    base.update(kw)
    return Track(**base)


def test_track_is_frozen():
    t = _track()
    try:
        t.title = "x"  # type: ignore[misc]
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("Track must be immutable")


def test_track_fields():
    t = _track(title="hello", duration=None)
    assert t.title == "hello"
    assert t.duration is None
    assert t.requester == "@r"


def test_repeat_mode_cycle():
    assert RepeatMode.OFF.next() == RepeatMode.ALL
    assert RepeatMode.ALL.next() == RepeatMode.ONE
    assert RepeatMode.ONE.next() == RepeatMode.OFF
