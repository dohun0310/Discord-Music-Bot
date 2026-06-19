from app.config import Colors
from app.domain.models import RepeatMode, Track
from app.ui.embeds import EmbedFactory


def _track(title="곡", duration=100.0):
    return Track(
        title=title, stream_url="http://s", webpage_url="http://w",
        duration=duration, thumbnail="http://thumb", uploader="u", requester="@r",
    )


def test_error_embed_color_and_text():
    e = EmbedFactory().error("문제 발생")
    assert e.color == Colors.ERROR
    assert "문제 발생" in e.description


def test_now_playing_contains_title_and_requester():
    e = EmbedFactory().now_playing(
        _track("내 노래"), volume=0.5, repeat_mode=RepeatMode.OFF, queue_size=0
    )
    assert "내 노래" in e.description
    assert "@r" in e.description


def test_track_added_shows_position():
    e = EmbedFactory().track_added(_track("곡"), queue_position=3)
    assert "#3" in e.description or "3" in str(e.to_dict())


def test_progress_adds_field():
    e = EmbedFactory().progress(
        _track(duration=100.0), volume=0.5, repeat_mode=RepeatMode.OFF,
        queue_size=1, position=50.0,
    )
    names = [f.name for f in e.fields]
    assert "진행률" in names


def test_queue_embed_lists_upcoming():
    f = EmbedFactory()
    e = f.queue(
        current=_track("현재곡"), position=10.0, paused=False,
        snapshot=[_track("다음1"), _track("다음2")],
        volume=0.5, repeat_mode=RepeatMode.ALL, max_display=10,
    )
    body = str(e.to_dict())
    assert "다음1" in body and "다음2" in body
