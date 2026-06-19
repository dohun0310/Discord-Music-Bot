from discord_music_bot.domain.models import Track
from discord_music_bot.services.audio import FFmpegSourceFactory


def _track():
    return Track(
        title="t", stream_url="http://stream", webpage_url="http://w",
        duration=None, thumbnail=None, uploader="u", requester="@r",
    )


class _FakeSource:
    def __init__(self, url, **opts):
        self.url = url
        self.opts = opts


class _FakeTransformer:
    def __init__(self, source, volume):
        self.source = source
        self.volume = volume


def test_create_wraps_stream_url_with_volume():
    factory = FFmpegSourceFactory(
        ffmpeg_options={"options": "-vn"},
        source_cls=_FakeSource,
        transformer_cls=_FakeTransformer,
    )
    result = factory.create(_track(), volume=0.7)
    assert isinstance(result, _FakeTransformer)
    assert result.volume == 0.7
    assert result.source.url == "http://stream"
    assert result.source.opts == {"options": "-vn"}
