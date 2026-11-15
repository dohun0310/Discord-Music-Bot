import pytest

from app.services.resolver import build_query


@pytest.mark.parametrize("query", [
    "helloworldx",         # 11자: YouTube 영상 ID 형식
    "PLaylistsongs",       # PL 접두사: 재생목록 ID 형식
    "RDbigbangfantastic",  # RD 접두사: 믹스 재생목록 ID 형식
    "NewJeans:Ditto",      # 콜론 앞부분이 URL 스킴으로 해석되는 형식
    "newjeans hypeboy",
    "아이유 좋은날",
])
def test_non_url_query_is_search(query):
    assert build_query(query) == ("ytsearch:" + query, True)


@pytest.mark.parametrize("query", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://youtu.be/dQw4w9WgXcQ",
    "Https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # 모바일 자동 대문자
])
def test_url_query_is_passed_through(query):
    assert build_query(query) == (query, False)


def test_url_without_scheme_gets_https():
    assert build_query("youtube.com/watch?v=dQw4w9WgXcQ") == (
        "https://youtube.com/watch?v=dQw4w9WgXcQ", False,
    )


async def test_resolve_sends_search_prefix_to_ytdl():
    from concurrent.futures import ThreadPoolExecutor

    from app.services.resolver import TrackResolution, YtDlpTrackResolver

    queries = []

    class _FakeYTDL:
        def __init__(self, opts):
            pass

        def extract_info(self, query, download=False):
            queries.append(query)
            return {"entries": [{"url": "http://s", "title": "곡", "webpage_url": "http://w"}]}

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        resolver = YtDlpTrackResolver(
            ytdl_options={}, batch_size=10, executor=executor, ytdl_factory=_FakeYTDL,
        )
        result = await resolver.resolve("helloworldx", "@r")
    finally:
        executor.shutdown(wait=False)
    assert queries == ["ytsearch:helloworldx"]
    assert isinstance(result, TrackResolution)
