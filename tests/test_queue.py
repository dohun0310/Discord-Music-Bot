import pytest

from app.domain.models import Track
from app.domain.queue import TrackQueue


def _track(title):
    return Track(
        title=title, stream_url="http://s/" + title, webpage_url="http://w",
        duration=None, thumbnail=None, uploader="u", requester="@r",
    )


def test_add_get_fifo():
    q = TrackQueue()
    q.add(_track("a"))
    q.add(_track("b"))
    assert q.size() == 2
    assert q.get().title == "a"
    assert q.get().title == "b"
    assert q.get() is None


def test_is_empty_and_clear():
    q = TrackQueue()
    assert q.is_empty()
    q.add(_track("a"))
    q.add(_track("b"))
    assert not q.is_empty()
    assert q.clear() == 2
    assert q.is_empty()


def test_snapshot_does_not_mutate():
    q = TrackQueue()
    q.add(_track("a"))
    snap = q.snapshot()
    snap.clear()
    assert q.size() == 1


def test_shuffle_needs_two():
    q = TrackQueue()
    q.add(_track("a"))
    assert q.shuffle() == 0
    q.add(_track("b"))
    assert q.shuffle() == 2


def test_remove_position_1based():
    q = TrackQueue()
    for name in ("a", "b", "c"):
        q.add(_track(name))
    removed = q.remove(2)
    assert removed.title == "b"
    assert [t.title for t in q.snapshot()] == ["a", "c"]


def test_remove_out_of_range_raises():
    q = TrackQueue()
    q.add(_track("a"))
    with pytest.raises(IndexError):
        q.remove(5)
    with pytest.raises(IndexError):
        q.remove(0)
