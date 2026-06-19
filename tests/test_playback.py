from discord_music_bot.domain.models import RepeatMode, Track
from discord_music_bot.domain.queue import TrackQueue
from discord_music_bot.domain.playback import decide_next_track


def _track(title):
    return Track(
        title=title, stream_url="http://s/" + title, webpage_url="http://w",
        duration=None, thumbnail=None, uploader="u", requester="@r",
    )


def test_off_returns_queue_head():
    q = TrackQueue()
    q.add(_track("a"))
    history: list = []
    nxt = decide_next_track(RepeatMode.OFF, None, q, history)
    assert nxt.title == "a"
    assert q.is_empty()
    assert history == []


def test_one_returns_current_without_consuming():
    q = TrackQueue()
    q.add(_track("a"))
    cur = _track("current")
    nxt = decide_next_track(RepeatMode.ONE, cur, q, [])
    assert nxt is cur
    assert q.size() == 1  # 큐를 소비하지 않음


def test_all_records_history():
    q = TrackQueue()
    q.add(_track("a"))
    history: list = []
    nxt = decide_next_track(RepeatMode.ALL, None, q, history)
    assert nxt.title == "a"
    assert [t.title for t in history] == ["a"]


def test_all_refills_from_history_when_empty():
    q = TrackQueue()
    history = [_track("a"), _track("b")]
    nxt = decide_next_track(RepeatMode.ALL, None, q, history)
    assert nxt.title == "a"
    # 히스토리에서 큐로 복원 후, 첫 곡을 다시 히스토리에 기록
    assert [t.title for t in q.snapshot()] == ["b"]
    assert [t.title for t in history] == ["a"]


def test_empty_returns_none():
    assert decide_next_track(RepeatMode.OFF, None, TrackQueue(), []) is None
