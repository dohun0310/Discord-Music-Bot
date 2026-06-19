from app.domain.models import Track
from app.services.resolver import (
    PlaylistResolution,
    TrackResolution,
    YtDlpTrackResolver,
    build_batch,
    build_resolution,
)


def _entry(**kw):
    base = dict(
        url="http://stream", title="제목", webpage_url="http://watch",
        duration=120, thumbnail="http://t", uploader="up", view_count=1,
    )
    base.update(kw)
    return base


def test_single_track_resolution():
    res = build_resolution(_entry(), query="http://watch", requester="@r", is_search=False)
    assert isinstance(res, TrackResolution)
    assert res.track.title == "제목"
    assert res.track.stream_url == "http://stream"
    assert res.track.requester == "@r"


def test_search_returns_first_valid():
    data = {"entries": [None, _entry(title="첫째"), _entry(title="둘째")]}
    res = build_resolution(data, query="검색어", requester="@r", is_search=True)
    assert isinstance(res, TrackResolution)
    assert res.track.title == "첫째"


def test_playlist_resolution_metadata():
    data = {
        "title": "내 리스트", "webpage_url": "http://list",
        "entries": [_entry(title="a"), _entry(title="b")],
    }
    res = build_resolution(data, query="http://list", requester="@r", is_search=False)
    assert isinstance(res, PlaylistResolution)
    assert res.title == "내 리스트"
    assert [t.title for t in res.tracks] == ["a", "b"]
    assert res.next_start_index == 1 + 2  # start(1) + 로드된 수


def test_missing_required_key_dropped():
    bad = _entry()
    del bad["url"]
    data = {"entries": [bad, _entry(title="ok")]}
    res = build_resolution(data, query="q", requester="@r", is_search=True)
    assert res.track.title == "ok"


def test_build_batch_returns_tracks():
    data = {"entries": [_entry(title="a"), _entry(title="b")]}
    tracks = build_batch(data, requester="@auto")
    assert [t.title for t in tracks] == ["a", "b"]
    assert all(isinstance(t, Track) for t in tracks)
    assert tracks[0].requester == "@auto"


def test_thumbnail_picks_highest_resolution():
    entry = _entry(thumbnail=None, thumbnails=[
        {"url": "low", "width": 10, "height": 10},
        {"url": "high", "width": 100, "height": 100},
    ])
    res = build_resolution(entry, query="q", requester="@r", is_search=False)
    assert res.track.thumbnail == "high"


async def test_resolve_uses_running_loop_without_injected_loop():
    """리졸버는 외부 주입 루프 없이 실행 중인 이벤트 루프를 사용해 동작해야 한다.

    회귀 방지: build_bot가 `bot.loop`을 생성 시점에 캡처하면 discord.py 2.x의
    `_LoopSentinel`이 들어와 재생 시 'loop attribute cannot be accessed' 오류가 났다.
    resolve()는 async 컨텍스트에서 스스로 running loop를 얻어야 한다.
    """
    from concurrent.futures import ThreadPoolExecutor

    class _FakeYTDL:
        def __init__(self, opts):
            pass

        def extract_info(self, query, download=False):
            return _entry(title="재생곡")

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        resolver = YtDlpTrackResolver(
            ytdl_options={}, batch_size=10, executor=executor, ytdl_factory=_FakeYTDL,
        )
        result = await resolver.resolve("검색어", "@user")
    finally:
        executor.shutdown(wait=False)

    assert isinstance(result, TrackResolution)
    assert result.track.title == "재생곡"
    assert result.track.stream_url == "http://stream"
