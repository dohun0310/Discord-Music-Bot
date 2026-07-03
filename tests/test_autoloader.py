from app.domain.models import Track
from app.player.autoloader import PlaylistAutoLoader


def _track(title):
    return Track(
        title=title, stream_url="http://s/" + title, webpage_url="http://w",
        duration=None, thumbnail=None, uploader="u", requester="@r",
    )


class _FakeResolver:
    """batches 리스트를 순서대로 반환. Exception 항목은 raise."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    async def load_playlist_batch(self, url, start_index, requester):
        self.calls.append((url, start_index, requester))
        item = self.batches.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _harness(loader):
    """(added, run_all) — spawn된 코루틴을 모아 실행하는 헬퍼."""
    added, pending = [], []

    def add_tracks(tracks):
        added.extend(tracks)
        return len(tracks)

    async def run_all():
        while pending:
            await pending.pop(0)

    def spawn(coro):
        pending.append(coro)

    return added, add_tracks, spawn, run_all


async def test_loads_batch_below_threshold_and_advances_index():
    resolver = _FakeResolver([[_track("a"), _track("b")], [_track("c")]])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 4, "@r")
    added, add_tracks, spawn, run_all = _harness(loader)

    loader.maybe_load(2, add_tracks, spawn)
    await run_all()
    assert [t.title for t in added] == ["a", "b"]
    assert resolver.calls[0] == ("http://list", 4, "@r")

    loader.maybe_load(0, add_tracks, spawn)
    await run_all()
    assert resolver.calls[1] == ("http://list", 6, "@r")  # 4 + 2


async def test_no_load_when_queue_at_threshold():
    resolver = _FakeResolver([])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    _, add_tracks, spawn, run_all = _harness(loader)
    loader.maybe_load(3, add_tracks, spawn)
    await run_all()
    assert resolver.calls == []


async def test_no_load_when_inactive():
    resolver = _FakeResolver([])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    _, add_tracks, spawn, run_all = _harness(loader)
    loader.maybe_load(0, add_tracks, spawn)
    await run_all()
    assert resolver.calls == []


async def test_no_double_load_before_first_finishes():
    resolver = _FakeResolver([[_track("a")]])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    _, add_tracks, spawn, run_all = _harness(loader)
    loader.maybe_load(0, add_tracks, spawn)
    loader.maybe_load(0, add_tracks, spawn)  # 아직 첫 로드 미완료 → 무시
    await run_all()
    assert len(resolver.calls) == 1


async def test_empty_batch_deactivates():
    resolver = _FakeResolver([[]])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    _, add_tracks, spawn, run_all = _harness(loader)
    loader.maybe_load(0, add_tracks, spawn)
    await run_all()
    assert loader.active is False


async def test_error_deactivates():
    resolver = _FakeResolver([RuntimeError("만료")])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    _, add_tracks, spawn, run_all = _harness(loader)
    loader.maybe_load(0, add_tracks, spawn)
    await run_all()
    assert loader.active is False
