import asyncio

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


class _GatedResolver:
    """gate가 열릴 때까지 로드를 지연시켜 in-flight 상태를 재현한다."""

    def __init__(self, tracks):
        self.tracks = tracks
        self.gate = asyncio.Event()
        self.calls = []

    async def load_playlist_batch(self, url, start_index, requester):
        self.calls.append((url, start_index, requester))
        await self.gate.wait()
        return self.tracks


async def test_clear_during_inflight_load_discards_results():
    resolver = _GatedResolver([_track("a")])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    added = []

    def add_tracks(tracks):
        added.extend(tracks)
        return len(tracks)

    tasks = []
    loader.maybe_load(0, add_tracks, lambda c: tasks.append(asyncio.ensure_future(c)))
    await asyncio.sleep(0)  # _load가 await 지점까지 진행
    loader.clear()          # 사용자가 대기열을 비움
    resolver.gate.set()
    await asyncio.gather(*tasks)
    assert added == []            # 폐기된 결과가 큐에 들어가지 않음
    assert loader.active is False


async def test_set_during_inflight_load_discards_old_batch():
    resolver = _GatedResolver([_track("옛곡")])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://old", 1, "@r")
    added = []

    def add_tracks(tracks):
        added.extend(tracks)
        return len(tracks)

    tasks = []
    loader.maybe_load(0, add_tracks, lambda c: tasks.append(asyncio.ensure_future(c)))
    await asyncio.sleep(0)
    loader.set("http://new", 5, "@r")  # 새 플레이리스트로 교체
    resolver.gate.set()
    await asyncio.gather(*tasks)
    assert added == []           # 옛 배치가 새 플레이리스트에 섞이지 않음
    assert loader.active is True  # 새 플레이리스트는 유지


async def test_next_index_advances_by_add_tracks_return_value():
    resolver = _FakeResolver([[_track("a"), _track("b"), _track("c")], [_track("d")]])
    loader = PlaylistAutoLoader(resolver=resolver, threshold=3)
    loader.set("http://list", 1, "@r")
    _, _, spawn, run_all = _harness(loader)

    def add_two_of_three(tracks):
        return len(tracks) - 1  # 한 곡이 거부된 상황

    loader.maybe_load(0, add_two_of_three, spawn)
    await run_all()
    loader.maybe_load(0, add_two_of_three, spawn)
    await run_all()
    assert resolver.calls[1][1] == 3  # 1 + 반환값 2 (len 3이 아니라)
